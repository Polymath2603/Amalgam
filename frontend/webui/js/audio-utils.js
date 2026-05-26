


export function int16ToFloat32(int16) {
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768.0;
  }
  return float32;
}


export function float32ToInt16(float32) {
  const int16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return int16;
}


export function base64ToInt16(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Int16Array(bytes.buffer);
}


export function int16ToBase64(int16) {
  const bytes = new Uint8Array(int16.buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}


export function calculateRMS(data, isByte = false) {
  let sumSquares = 0;
  const len = data.length;
  if (len === 0) return 0;

  for (let i = 0; i < len; i++) {
    const value = isByte ? (data[i] - 128) / 128 : data[i];
    sumSquares += value * value;
  }
  return Math.sqrt(sumSquares / len);
}


export function zeroCrossingRate(data) {
  if (data.length < 2) return 0;
  let crossings = 0;
  for (let i = 1; i < data.length; i++) {
    if ((data[i] >= 0 && data[i - 1] < 0) || (data[i] < 0 && data[i - 1] >= 0)) {
      crossings++;
    }
  }
  return crossings / (data.length - 1);
}


export function extractBandEnergies(frequencyData, sampleRate, bands) {
  const defaultBands = bands || [
    { name: 'sub',      min: 20,   max: 200  },  
    { name: 'low',      min: 200,  max: 800  },  
    { name: 'mid',      min: 800,  max: 2500 },  
    { name: 'high',     min: 2500, max: 5500 },  
    { name: 'veryHigh', min: 5500, max: 12000 }, 
  ];

  const binCount = frequencyData.length;
  const nyquist = sampleRate / 2;
  const binWidth = nyquist / binCount;
  const result = {};

  for (const band of defaultBands) {
    const startBin = Math.max(0, Math.floor(band.min / binWidth));
    const endBin = Math.min(binCount - 1, Math.floor(band.max / binWidth));
    
    if (startBin >= endBin) {
      result[band.name] = 0;
      continue;
    }

    let sum = 0;
    let count = 0;
    for (let i = startBin; i <= endBin; i++) {
      sum += frequencyData[i] / 255;
      count++;
    }
    result[band.name] = count > 0 ? sum / count : 0;
  }

  return result;
}


export function smoothValue(current, target, factor) {
  return current + (target - current) * (1 - factor);
}


export function lerp(a, b, t) {
  return a + (b - a) * Math.max(0, Math.min(1, t));
}


export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}


export function resample(input, fromRate, toRate) {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const outputLength = Math.round(input.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i++) {
    const srcIndex = i * ratio;
    const low = Math.floor(srcIndex);
    const high = Math.min(low + 1, input.length - 1);
    const frac = srcIndex - low;
    output[i] = input[low] * (1 - frac) + input[high] * frac;
  }
  return output;
}
