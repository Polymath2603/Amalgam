import { createRequire } from 'module';
const require = createRequire(import.meta.url);

if (typeof globalThis.FileReader === 'undefined') {
  globalThis.FileReader = class FileReader {
    constructor() { this.result = null; this.onload = null; this.onloadend = null; }
    readAsArrayBuffer(blob) {
      blob.arrayBuffer().then(buf => {
        this.result = buf;
        if (this.onloadend) this.onloadend({ target: this });
        if (this.onload) this.onload({ target: this });
      });
    }
    readAsDataURL(blob) {
      blob.arrayBuffer().then(buf => {
        this.result = 'data:application/octet-stream;base64,' + Buffer.from(buf).toString('base64');
        if (this.onloadend) this.onloadend({ target: this });
        if (this.onload) this.onload({ target: this });
      });
    }
  };
}

const THREE = require('three');
const { BVHLoader } = require('three/examples/jsm/loaders/BVHLoader.js');
const { GLTFExporter } = require('three/examples/jsm/exporters/GLTFExporter.js');

import { readFileSync, writeFileSync, readdirSync, existsSync, mkdirSync } from 'fs';
import { join, dirname, basename, extname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ANIM_DIR = join(__dirname, '..', 'characters', 'default', 'anim');

const _v3A = new THREE.Vector3();

function getRootBone(skeleton) {
  const boneSet = new Set(skeleton.bones);
  for (const bone of skeleton.bones) {
    if (bone.parent == null || !boneSet.has(bone.parent)) return bone;
  }
  throw new Error('Invalid skeleton. Could not find root bone.');
}

function objectTraverseFilter(root, fn) {
  const result = [];
  root.traverse((obj) => { if (fn(obj)) result.push(obj); });
  return result;
}

function pickByProbability(objects, evaluators) {
  if (objects.length === 0) return null;
  const weights = objects.map((obj) =>
    evaluators.reduce((sum, e) => sum + e.func(obj) * e.weight, 0.0)
  );
  const totalWeight = weights.reduce((a, b) => a + b, 0.0);
  if (totalWeight <= 0) return objects[Math.floor(Math.random() * objects.length)];
  let r = Math.random() * totalWeight;
  for (let i = 0; i < objects.length; i++) {
    r -= weights[i];
    if (r <= 0) return objects[i];
  }
  return objects[objects.length - 1];
}

function evaluatorEqual(obj, another) {
  return obj === another ? 1 : 0;
}

function evaluatorName(obj, substring) {
  return obj.name.toLowerCase().includes(substring) ? 1 : 0;
}

function determineSpineBones(hips, chestCand) {
  const spineBones = [];
  let current = chestCand;
  while (current) {
    spineBones.unshift(current);
    if (current === hips) break;
    current = current.parent;
  }
  if (spineBones.length < 3) throw new Error('Not enough spine bones.');
  if (spineBones.length === 3) return [spineBones[1], spineBones[2], null];
  return [spineBones[Math.floor((spineBones.length - 1) / 3.0)], spineBones[Math.floor(((spineBones.length - 1) / 3.0) * 2.0)], spineBones[spineBones.length - 1]];
}

function determineLegBones(legRoot) {
  const bones = [];
  let current = legRoot;
  let depth = 0;
  while (current) {
    const firstChild = current.children[0];
    bones.push({ bone: current, depth, len: firstChild ? firstChild.position.length() : 0 });
    current = firstChild;
    depth++;
  }
  if (bones.length < 3) throw new Error('Not enough leg bones.');
  const sorted = [...bones].sort((a, b) => b.len - a.len);
  const upperLeg = sorted[0], lowerLeg = sorted[1];
  const foot = bones[lowerLeg.depth + 1];
  if (!foot) throw new Error('Could not find foot bone.');
  const toes = bones[foot.depth + 1];
  return [upperLeg.bone, lowerLeg.bone, foot.bone, toes?.bone || null];
}

function determineArmBones(armRoot) {
  const bones = [];
  let current = armRoot;
  let depth = 0;
  while (current) {
    const firstChild = current.children[0];
    bones.push({ bone: current, depth, len: firstChild ? firstChild.position.length() : 0 });
    current = firstChild;
    depth++;
  }
  if (bones.length < 3) throw new Error('Not enough arm bones.');
  const sorted = [...bones].sort((a, b) => b.len - a.len);
  const upperArm = sorted[0], lowerArm = sorted[1];
  const hand = bones[lowerArm.depth + 1];
  if (!hand) throw new Error('Could not find hand bone.');
  const shoulder = upperArm.depth !== 0 ? bones[upperArm.depth - 1] : null;
  return [shoulder?.bone || null, upperArm.bone, lowerArm.bone, hand.bone];
}

function determineHeadBones(headRoot) {
  let head = headRoot;
  while (head.children.length === 1) head = head.children[0];
  const neck = headRoot === head ? null : headRoot;
  let leftEye = null, rightEye = null;
  return [neck, head, leftEye, rightEye];
}

function mapSkeletonToVRM(root) {
  const result = new Map();
  const objectBFS = (root, fn) => {
    const queue = [root];
    while (queue.length > 0) {
      const obj = queue.shift();
      if (fn(obj)) return obj;
      queue.push(...obj.children);
    }
    return null;
  };

  const hips = objectBFS(root, (obj) => obj.children.length >= 3);
  if (!hips) throw new Error('Cannot find hips.');
  result.set('hips', hips);

  const chestCands = objectTraverseFilter(hips, (obj) => obj !== hips && obj.children.length >= 3);
  const chestCand = pickByProbability(chestCands, [
    { func: (obj) => evaluatorName(obj, 'upperchest'), weight: 1.0 },
    { func: (obj) => evaluatorName(obj, 'chest'), weight: 1.0 },
  ]);
  if (!chestCand) throw new Error('Cannot find chest.');

  const [spine, chest, upperChest] = determineSpineBones(hips, chestCand);
  result.set('spine', spine);
  result.set('chest', chest);
  if (upperChest) result.set('upperChest', upperChest);

  const leftLegRoot = pickByProbability(hips.children, [
    { func: (obj) => evaluatorName(obj, 'leftupperleg'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'l_upperleg'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'leg'), weight: 1.0 },
    { func: (obj) => obj.getWorldPosition(_v3A).x, weight: 1.0 },
  ]);
  const rightLegRoot = pickByProbability(hips.children, [
    { func: (obj) => evaluatorEqual(obj, leftLegRoot), weight: -100.0 },
    { func: (obj) => evaluatorName(obj, 'rightupperleg'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'r_upperleg'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'leg'), weight: 1.0 },
    { func: (obj) => -obj.getWorldPosition(_v3A).x, weight: 1.0 },
  ]);

  const [lUpperLeg, lLowerLeg, lFoot, lToes] = determineLegBones(leftLegRoot);
  result.set('leftUpperLeg', lUpperLeg);
  result.set('leftLowerLeg', lLowerLeg);
  result.set('leftFoot', lFoot);
  if (lToes) result.set('leftToes', lToes);

  const [rUpperLeg, rLowerLeg, rFoot, rToes] = determineLegBones(rightLegRoot);
  result.set('rightUpperLeg', rUpperLeg);
  result.set('rightLowerLeg', rLowerLeg);
  result.set('rightFoot', rFoot);
  if (rToes) result.set('rightToes', rToes);

  const leftArmRoot = pickByProbability(chestCand.children, [
    { func: (obj) => evaluatorName(obj, 'leftshoulder'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'l_shoulder'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'leftupperarm'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'l_upperarm'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'shoulder'), weight: 1.0 },
    { func: (obj) => evaluatorName(obj, 'arm'), weight: 1.0 },
    { func: (obj) => obj.getWorldPosition(_v3A).x, weight: 1.0 },
  ]);
  const rightArmRoot = pickByProbability(chestCand.children, [
    { func: (obj) => evaluatorEqual(obj, leftArmRoot), weight: -100.0 },
    { func: (obj) => evaluatorName(obj, 'rightshoulder'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'r_shoulder'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'rightupperarm'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'r_upperarm'), weight: 10.0 },
    { func: (obj) => evaluatorName(obj, 'shoulder'), weight: 1.0 },
    { func: (obj) => evaluatorName(obj, 'arm'), weight: 1.0 },
    { func: (obj) => -obj.getWorldPosition(_v3A).x, weight: 1.0 },
  ]);
  const headRoot = pickByProbability(chestCand.children, [
    { func: (obj) => evaluatorEqual(obj, leftArmRoot), weight: -100.0 },
    { func: (obj) => evaluatorEqual(obj, rightArmRoot), weight: -100.0 },
    { func: (obj) => evaluatorName(obj, 'neck'), weight: 1.0 },
    { func: (obj) => evaluatorName(obj, 'head'), weight: 1.0 },
    { func: (obj) => Math.abs(obj.getWorldPosition(_v3A).x), weight: -1.0 },
  ]);

  const [lShoulder, lUpperArm, lLowerArm, lHand] = determineArmBones(leftArmRoot);
  if (lShoulder) result.set('leftShoulder', lShoulder);
  result.set('leftUpperArm', lUpperArm);
  result.set('leftLowerArm', lLowerArm);
  result.set('leftHand', lHand);

  const [rShoulder, rUpperArm, rLowerArm, rHand] = determineArmBones(rightArmRoot);
  if (rShoulder) result.set('rightShoulder', rShoulder);
  result.set('rightUpperArm', rUpperArm);
  result.set('rightLowerArm', rLowerArm);
  result.set('rightHand', rHand);

  const [neck, head, leftEye, rightEye] = determineHeadBones(headRoot);
  if (neck) result.set('neck', neck);
  result.set('head', head);
  if (leftEye) result.set('leftEye', leftEye);
  if (rightEye) result.set('rightEye', rightEye);

  return result;
}

function createSkeletonBoundingBox(skeleton) {
  const bb = new THREE.Box3();
  for (const bone of skeleton.bones) bb.expandByPoint(bone.getWorldPosition(_v3A));
  return bb;
}

async function convertBVHToVRMAnimation(bvh, scale = 0.01) {
  const skeleton = bvh.skeleton.clone();
  const clip = bvh.clip.clone();
  const rootBone = getRootBone(skeleton);

  rootBone.traverse((bone) => { bone.position.multiplyScalar(scale); });
  rootBone.updateWorldMatrix(false, true);

  const vrmBoneMap = mapSkeletonToVRM(rootBone);
  rootBone.userData.vrmBoneMap = vrmBoneMap;

  const hipsBone = vrmBoneMap.get('hips');
  const hipsBoneName = hipsBone.name;
  let hipsPositionTrack = null;

  const spineBone = vrmBoneMap.get('spine');
  const spineBoneName = spineBone.name;
  let spinePositionTrack = null;

  const filteredTracks = [];
  for (const origTrack of bvh.clip.tracks) {
    const track = origTrack.clone();
    track.name = track.name.replace(/\.bones\[(.*)\]/, '$1');
    if (track.name.endsWith('.quaternion')) {
      filteredTracks.push(track);
    }
    if (track.name === `${hipsBoneName}.position`) {
      const newTrack = track.clone();
      newTrack.values = track.values.map(v => v * scale);
      hipsPositionTrack = newTrack;
      filteredTracks.push(newTrack);
    }
    if (track.name === `${spineBoneName}.position`) {
      const newTrack = track.clone();
      newTrack.values = track.values.map(v => v * scale);
      spinePositionTrack = newTrack;
    }
  }

  clip.tracks = filteredTracks;

  if (hipsPositionTrack) {
    const offset = hipsBone.position.toArray();
    for (let i = 0; i < hipsPositionTrack.values.length; i++) {
      hipsPositionTrack.values[i] -= offset[i % 3];
    }
  }

  const boundingBox = createSkeletonBoundingBox(skeleton);
  if (boundingBox.min.y < 0) rootBone.position.y -= boundingBox.min.y;

  const exporter = new GLTFExporter();
  const vrmBoneNames = [];
  for (const [boneName] of vrmBoneMap) vrmBoneNames.push(boneName);

  exporter.register((writer) => ({
    name: 'VRMC_vrm_animation',
    afterParse(input) {
      if (!Array.isArray(input)) return;
      const root = input[0];
      const boneMap = root.userData?.vrmBoneMap;
      if (!boneMap) return;

      const humanBones = {};
      for (const [boneName, bone] of boneMap) {
        const node = writer.nodeMap.get(bone);
        if (node != null) humanBones[boneName] = { node };
      }
      const extension = {
        specVersion: '1.0',
        humanoid: { humanBones },
      };
      const gltfDef = writer.json;
      gltfDef.extensionsUsed = gltfDef.extensionsUsed || [];
      gltfDef.extensionsUsed.push('VRMC_vrm_animation');
      gltfDef.extensions = gltfDef.extensions || {};
      gltfDef.extensions['VRMC_vrm_animation'] = extension;
    },
  }));

  const gltf = await exporter.parseAsync(rootBone, { animations: [clip], binary: true });
  return gltf;
}

async function convertFile(inputPath, outputPath) {
  const data = readFileSync(inputPath);
  const ext = extname(inputPath).toLowerCase();

  if (ext === '.bvh') {
    const loader = new BVHLoader();
    const bvh = loader.parse(data.toString('utf8'));
    const result = await convertBVHToVRMAnimation(bvh, 0.01);
    writeFileSync(outputPath, Buffer.from(result));
    console.log(`  ✓ ${basename(inputPath)} → ${basename(outputPath)} (${(result.byteLength / 1024).toFixed(0)}KB)`);
  } else if (ext === '.fbx') {
    const { FBXLoader } = require('three/examples/jsm/loaders/FBXLoader.js');
    const fbxLoader = new FBXLoader();
    const scene = fbxLoader.parse(data);
    const skeleton = scene.getObjectByProperty('type', 'Bone')?.parent?.children?.[0]?.skeleton;
    if (!skeleton) throw new Error('No skeleton found in FBX');
    const bvh = { skeleton, clip: scene.animations[0] };
    if (!bvh.clip) throw new Error('No animation clip found in FBX');
    const result = await convertBVHToVRMAnimation(bvh, 0.01);
    writeFileSync(outputPath, Buffer.from(result));
    console.log(`  ✓ ${basename(inputPath)} → ${basename(outputPath)} (${(result.byteLength / 1024).toFixed(0)}KB)`);
  } else {
    console.log(`  - ${basename(inputPath)}: unsupported format`);
  }
}

async function main() {
  const existingFiles = new Set();
  if (existsSync(ANIM_DIR)) {
    for (const f of readdirSync(ANIM_DIR)) existingFiles.add(f.toLowerCase());
  } else {
    mkdirSync(ANIM_DIR, { recursive: true });
  }

  const inputDir = join(__dirname, '..', '..', '..', 'cloned', 'ST-pack', 'bvh_to_convert');
  if (!existsSync(inputDir)) {
    console.error(`Input dir not found: ${inputDir}`);
    process.exit(1);
  }

  const files = readdirSync(inputDir).sort();
  let converted = 0, skipped = 0, failed = 0;

  for (const f of files) {
    const ext = extname(f).toLowerCase();
    if (ext !== '.bvh' && ext !== '.fbx') continue;

    const base = basename(f, extname(f));
    const outName = `${base}.vrma`.toLowerCase();
    if (existingFiles.has(outName)) {
      console.log(`  - ${f}: already exists, skipping`);
      skipped++;
      continue;
    }

    try {
      await convertFile(join(inputDir, f), join(ANIM_DIR, outName));
      converted++;
    } catch (e) {
      console.error(`  ✗ ${f}: ERROR - ${e.message}`);
      failed++;
    }
  }

  console.log(`\nDone: ${converted} converted, ${skipped} skipped, ${failed} failed`);
}

main().catch(console.error);
