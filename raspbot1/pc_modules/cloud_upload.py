"""Upload alarm-triggered snapshots to Aliyun OSS."""

import asyncio
import json
import os
import time
from datetime import datetime, timezone, timedelta

from .logger_setup import setup_logger

logger = setup_logger('raspbot.cloud_upload')

# Aliyun OSS SDK may not be installed; defer import to upload time.
_oss2 = None

_UPLOAD_ALARM_TOKENS = frozenset({'cry', 'smoke', 'cliff', 'temp_high', 'temp_low'})

_BEIJING_TZ = timezone(timedelta(hours=8))


def _load_config():
    """Load OSS config from raspbot.local.json, falling back to env vars."""
    config = {
        'endpoint': os.getenv('RASPBOT_OSS_ENDPOINT', 'oss-cn-hangzhou.aliyuncs.com'),
        'bucket': os.getenv('RASPBOT_OSS_BUCKET', ''),
        'access_key_id': os.getenv('RASPBOT_OSS_ACCESS_KEY_ID', ''),
        'access_key_secret': os.getenv('RASPBOT_OSS_ACCESS_KEY_SECRET', ''),
        'upload_enabled': os.getenv('RASPBOT_OSS_UPLOAD_ENABLED', '') not in ('0', 'false', 'no'),
        'alarm_cooldown_sec': float(os.getenv('RASPBOT_OSS_ALARM_COOLDOWN_SEC', '30')),
        'global_cooldown_sec': float(os.getenv('RASPBOT_OSS_GLOBAL_COOLDOWN_SEC', '10')),
    }
    local_path = os.path.join(os.path.dirname(__file__), '..', 'raspbot.local.json')
    try:
        with open(local_path, 'r') as fh:
            local = json.load(fh)
        oss_cfg = local.get('aliyun_oss', {})
        if isinstance(oss_cfg, dict):
            for key in config:
                if key in oss_cfg:
                    config[key] = oss_cfg[key]
    except Exception:
        pass
    return config


class CloudUploader:
    """Uploads the latest video JPEG to Aliyun OSS on relevant alarms."""

    def __init__(self, config: dict = None):
        cfg = config if config is not None else _load_config()
        self.endpoint = str(cfg.get('endpoint', ''))
        self.bucket_name = str(cfg.get('bucket', ''))
        self.access_key_id = str(cfg.get('access_key_id', ''))
        self.access_key_secret = str(cfg.get('access_key_secret', ''))
        self.enabled = bool(cfg.get('upload_enabled', False))
        self.alarm_cooldown_sec = float(cfg.get('alarm_cooldown_sec', 30))
        self.global_cooldown_sec = float(cfg.get('global_cooldown_sec', 10))
        self._last_by_token = {}
        self._last_global = 0.0
        self._seq = 0
        if self.enabled:
            if not self.endpoint or not self.bucket_name or not self.access_key_id:
                logger.warning('cloud upload enabled but OSS config incomplete, disabled')
                self.enabled = False
            else:
                logger.info('cloud upload enabled bucket=%s endpoint=%s', self.bucket_name, self.endpoint)

    def _wants_upload(self, alarm_str: str) -> bool:
        """Check cooldowns and return whether to upload."""
        if not self.enabled:
            return False
        tokens = set(alarm_str.replace(';', '+').replace(',', '+').split('+'))
        relevant = tokens & _UPLOAD_ALARM_TOKENS
        if not relevant:
            return False
        now = time.monotonic()
        if now - self._last_global < self.global_cooldown_sec:
            return False
        for token in relevant:
            last = self._last_by_token.get(token, 0.0)
            if now - last >= self.alarm_cooldown_sec:
                self._last_global = now
                self._last_by_token[token] = now
                return True
        return False

    async def upload(self, jpeg_bytes: bytes, alarm_str: str) -> bool:
        """Upload JPEG to OSS. Returns True on success."""
        if not self._wants_upload(alarm_str):
            return False
        self._seq += 1
        seq = self._seq
        # Run blocking OSS upload in a thread.
        return await asyncio.to_thread(self._upload_sync, jpeg_bytes, alarm_str, seq)

    def _upload_sync(self, jpeg_bytes: bytes, alarm_str: str, seq: int) -> bool:
        global _oss2
        if _oss2 is None:
            try:
                import oss2 as _mod
                _oss2 = _mod
            except ImportError:
                logger.error('oss2 not installed, cannot upload')
                self.enabled = False
                return False
        now = datetime.now(_BEIJING_TZ)
        date_dir = now.strftime('%Y-%m-%d')
        safe_alarm = alarm_str.replace('+', '_').replace(';', '_')[:40]
        key = f'alarms/{date_dir}/{safe_alarm}_{now.strftime("%H%M%S")}_f{seq}.jpg'
        try:
            auth = _oss2.Auth(self.access_key_id, self.access_key_secret)
            bucket = _oss2.Bucket(auth, self.endpoint, self.bucket_name)
            bucket.put_object(key, jpeg_bytes, headers={'Content-Type': 'image/jpeg'})
            logger.info('uploaded %s (%d bytes)', key, len(jpeg_bytes))
            return True
        except Exception as exc:
            logger.error('upload failed: %s: %s', key, exc)
            return False

    # ---- Snapshot listing / download for App (via signaling) ----

    def _get_bucket(self):
        global _oss2
        if _oss2 is None:
            try:
                import oss2 as _mod
                _oss2 = _mod
            except ImportError:
                return None
        auth = _oss2.Auth(self.access_key_id, self.access_key_secret)
        return _oss2.Bucket(auth, self.endpoint, self.bucket_name)

    def list_snapshots(self, prefix: str = 'alarms/', max_keys: int = 40) -> list:
        """Return list of dicts with keys: key, date_dir, time_str, alarm_type."""
        if not self.enabled:
            return []
        bucket = self._get_bucket()
        if bucket is None:
            return []
        results = []
        try:
            for obj in bucket.list_objects(prefix=prefix, max_keys=max_keys).object_list:
                if not obj.key.endswith('.jpg'):
                    continue
                parsed = self._parse_snapshot_key(obj.key)
                if parsed:
                    results.append(parsed)
        except Exception as exc:
            logger.error('list snapshots failed: %s', exc)
        results.sort(key=lambda x: x.get('date_dir', '') + x.get('time_str', ''), reverse=True)
        return results[:max_keys]

    def download_snapshot(self, key: str) -> bytes:
        """Download snapshot bytes from OSS. Returns empty bytes on failure."""
        if not self.enabled:
            return b''
        bucket = self._get_bucket()
        if bucket is None:
            return b''
        try:
            result = bucket.get_object(key)
            return result.read()
        except Exception as exc:
            logger.error('download snapshot failed: %s: %s', key, exc)
            return b''

    @staticmethod
    def _parse_snapshot_key(key: str) -> dict:
        parts = key.split('/')
        if len(parts) < 3:
            return {}
        date_dir = parts[1]
        filename = parts[-1]
        name_parts = filename.split('_')
        if len(name_parts) < 2:
            return {}
        return {
            'key': key,
            'date_dir': date_dir,
            'time_str': name_parts[1] if len(name_parts) > 1 else '',
            'alarm_type': name_parts[0],
        }
