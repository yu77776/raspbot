// 主入口：组装全部幻灯片并导出
const D = require("./build_defense_deck.js");
require("./deck_part2.js"); // 链式加载 part1 + part2 的所有 IIFE
const { pptx, K, OUT, JSZip, fs, path } = D;

const finalPath = path.join(OUT, "基于树莓派的婴幼儿智能陪护小车系统设计-答辩PPT-夜间监护版.pptx");

async function addFade(file) {
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const slideFiles = Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n));
  for (const sp of slideFiles) {
    let xml = await zip.file(sp).async("string");
    if (xml.includes("<p:transition")) continue;
    xml = xml.replace(/(<p:cSld\b)/, '<p:transition spd="med"><p:fade/></p:transition>$1');
    zip.file(sp, xml);
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

pptx.writeFile({ fileName: finalPath })
  .then(() => addFade(finalPath))
  .then(() => console.log("OK:", finalPath))
  .catch((e) => { console.error("FAIL:", e); process.exit(1); });
