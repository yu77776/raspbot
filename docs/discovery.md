# Raspbot Discovery Service

The car can broadcast its current IP independently from the main car server.

- Script: `/home/pi/raspbot/discovery_broadcaster.py`
- Service: `raspbot-discovery.service`
- UDP broadcast port: `5002`
- Main websocket port advertised: `5001`

Payload example:

```json
{"name":"raspbot","role":"car","ip":"10.188.152.100","ips":["10.188.152.100"],"port":5001,"server_running":true,"hostname":"pi","seq":1,"ts":1710000000}
```

Install on the car:

```bash
sudo cp /home/pi/raspbot/systemd/raspbot-discovery.service /etc/systemd/system/raspbot-discovery.service
sudo systemctl daemon-reload
sudo systemctl enable --now raspbot-discovery.service
systemctl status raspbot-discovery.service
```

PC/App should listen for UDP packets on port `5002`, then connect to `ip:port`.

PC startup behavior:

```bash
cd /home-or-windows-path/raspbot1
python pc_client_ws.py
```

The PC client listens on UDP `5002` for about 3 seconds. If a car is found, it
connects to the broadcast `ip:port`. If not found, it falls back to
`DEFAULT_CAR_HOST`.

Disable discovery when needed:

```bash
python pc_client_ws.py --no-discover --host 10.188.152.100 --port 5001
```
