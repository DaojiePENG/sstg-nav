export async function loadPGM(pgmUrl: string, yamlUrl: string) {
  const yamlResponse = await fetch(yamlUrl);
  const yamlText = await yamlResponse.text();
  
  const config = {
    resolution: 0.05,
    origin: [0, 0, 0],
    occupied_thresh: 0.65,
    free_thresh: 0.196,
    negate: 0
  };
  
  const lines = yamlText.split("\n");
  for (const line of lines) {
    const parts = line.split(":");
    if (parts.length < 2) continue;
    const key = parts[0].trim();
    const valStr = parts.slice(1).join(":").trim();
    
    if (key === "resolution") config.resolution = parseFloat(valStr);
    if (key === "occupied_thresh") config.occupied_thresh = parseFloat(valStr);
    if (key === "free_thresh") config.free_thresh = parseFloat(valStr);
    if (key === "negate") config.negate = parseInt(valStr);
    if (key === "origin") {
      const arr = valStr.replace(/[\[\]]/g, "").split(",").map(s => parseFloat(s.trim()));
      if (arr.length >= 3) config.origin = [arr[0], arr[1], arr[2]];
    }
  }

  const pgmResponse = await fetch(pgmUrl);
  const buffer = await pgmResponse.arrayBuffer();
  const view = new DataView(buffer);
  
  let offset = 0;
  
  function readNextToken() {
    let token = "";
    while (offset < buffer.byteLength) {
      const char = String.fromCharCode(view.getUint8(offset++));
      if (char === " " || char === "\n" || char === "\r" || char === "\t") {
        if (token.length > 0) return token;
      } else if (char === "#") {
        while (offset < buffer.byteLength && String.fromCharCode(view.getUint8(offset)) !== "\n") {
          offset++;
        }
      } else {
        token += char;
      }
    }
    return token;
  }

  const magic = readNextToken();
  const widthStr = readNextToken();
  const heightStr = readNextToken();
  const maxValStr = readNextToken();
  
  if (magic !== "P5") throw new Error("Invalid PGM format.");
  
  const width = parseInt(widthStr);
  const height = parseInt(heightStr);
  const maxVal = parseInt(maxValStr);
  
  const pixels = new Uint8Array(buffer, offset);
  
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Could not create canvas context");
  
  const imgData = ctx.createImageData(width, height);
  
  for (let i = 0; i < pixels.length; i++) {
    let p = pixels[i];
    const p_norm = p / maxVal;
    let p_mapped = config.negate ? p_norm : 1.0 - p_norm;

    let color = [148, 163, 184]; // Unknown
    if (p_mapped > config.occupied_thresh) color = [30, 41, 59]; // Occupied
    else if (p_mapped < config.free_thresh) color = [241, 245, 249]; // Free
    
    const x = i % width;
    const y = Math.floor(i / width);
    const flippedY = height - 1 - y; // ROS flips Y
    
    const dataIdx = (flippedY * width + x) * 4;
    imgData.data[dataIdx] = color[0];
    imgData.data[dataIdx + 1] = color[1];
    imgData.data[dataIdx + 2] = color[2];
    imgData.data[dataIdx + 3] = 255;
  }
  
  ctx.putImageData(imgData, 0, 0);
  
  return { canvas, width, height, config };
}
