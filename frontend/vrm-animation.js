

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMHumanBoneName, VRMHumanBoneParentMap, VRMExpressionPresetName } from '@pixiv/three-vrm';



function arrayChunk(array, every) {
    const N = array.length;
    const ret = [];
    let current = [];
    let remaining = 0;
    for (let i = 0; i < N; i++) {
        if (remaining <= 0) {
            remaining = every;
            current = [];
            ret.push(current);
        }
        current.push(array[i]);
        remaining--;
    }
    return ret;
}



export class VRMAnimation {
    constructor() {
        this.duration = 0.0;
        this.restHipsPosition = new THREE.Vector3();
        this.humanoidTracks = {
            translation: new Map(),
            rotation: new Map(),
        };
        this.expressionTracks = new Map();
        this.lookAtTrack = null;
    }

    createAnimationClip(vrm) {
        const tracks = [];
        tracks.push(...this.createHumanoidTracks(vrm));
        if (vrm.expressionManager != null) {
            tracks.push(...this.createExpressionTracks(vrm.expressionManager));
        }
        if (vrm.lookAt != null) {
            const track = this.createLookAtTrack('lookAtTargetParent.quaternion');
            if (track != null) tracks.push(track);
        }
        return new THREE.AnimationClip('Clip', this.duration, tracks);
    }

    createHumanoidTracks(vrm) {
        const humanoid = vrm.humanoid;
        const metaVersion = vrm.meta.metaVersion;
        const tracks = [];

        for (const [name, origTrack] of this.humanoidTracks.rotation.entries()) {
            const nodeName = humanoid.getNormalizedBoneNode(name)?.name;
            if (nodeName != null) {
                const newValues = [];
                const metaVersionZero = metaVersion === '0';
                let sign = metaVersionZero ? -1 : 1;
                let opposite = metaVersionZero ? 1 : 1;
                let prevQuaternion = new THREE.Quaternion();

                if (origTrack.values.length % 4 !== 0) continue;

                for (let i = 0; i < origTrack.values.length; i += 4) {
                    const quaternion = new THREE.Quaternion(
                        origTrack.values[i], origTrack.values[i + 1],
                        origTrack.values[i + 2], origTrack.values[i + 3]
                    );
                    if (prevQuaternion.dot(quaternion) < 0 && metaVersionZero) {
                        sign *= -1;
                        opposite *= -1;
                    }
                    newValues.push(
                        sign * origTrack.values[i],
                        opposite * origTrack.values[i + 1],
                        sign * origTrack.values[i + 2],
                        opposite * origTrack.values[i + 3]
                    );
                    prevQuaternion = quaternion;
                }
                const track = origTrack.clone();
                track.values = new Float32Array(newValues);
                track.name = `${nodeName}.quaternion`;
                tracks.push(track);
            }
        }

        for (const [name, origTrack] of this.humanoidTracks.translation.entries()) {
            const nodeName = humanoid.getNormalizedBoneNode(name)?.name;
            if (nodeName != null) {
                const animationY = this.restHipsPosition.y;
                const humanoidY = humanoid.getNormalizedAbsolutePose().hips.position[1];
                const scale = humanoidY / animationY;

                const track = origTrack.clone();
                track.values = track.values.map(
                    (v, i) => (metaVersion === '0' && i % 3 !== 1 ? -v : v) * scale
                );
                track.name = `${nodeName}.position`;
                tracks.push(track);
            }
        }

        return tracks;
    }

    createExpressionTracks(expressionManager) {
        const tracks = [];
        for (const [name, origTrack] of this.expressionTracks.entries()) {
            const trackName = expressionManager.getExpressionTrackName(name);
            if (trackName != null) {
                const track = origTrack.clone();
                track.name = trackName;
                tracks.push(track);
            }
        }
        return tracks;
    }

    createLookAtTrack(trackName) {
        if (this.lookAtTrack == null) return null;
        const track = this.lookAtTrack.clone();
        track.name = trackName;
        return track;
    }
}



const MAT4_IDENTITY = new THREE.Matrix4();
const _v3A = new THREE.Vector3();
const _quatA = new THREE.Quaternion();
const _quatB = new THREE.Quaternion();
const _quatC = new THREE.Quaternion();

export class VRMAnimationLoaderPlugin {
    constructor(parser) {
        this.parser = parser;
        this.name = 'VRMC_vrm_animation';
    }

    async afterRoot(gltf) {
        const defGltf = gltf.parser.json;
        const defExtensionsUsed = defGltf.extensionsUsed;

        if (defExtensionsUsed == null || defExtensionsUsed.indexOf(this.name) === -1) return;

        const defExtension = defGltf.extensions?.[this.name];
        if (defExtension == null) return;

        const nodeMap = this._createNodeMap(defExtension);
        const worldMatrixMap = await this._createBoneWorldMatrixMap(gltf, defExtension);

        const hipsNode = defExtension.humanoid.humanBones['hips'].node;
        const hips = await gltf.parser.getDependency('node', hipsNode);
        const restHipsPosition = hips.getWorldPosition(new THREE.Vector3());

        const clips = gltf.animations;
        const animations = clips.map((clip, iAnimation) => {
            const defAnimation = defGltf.animations[iAnimation];
            const animation = this._parseAnimation(clip, defAnimation, nodeMap, worldMatrixMap);
            animation.restHipsPosition = restHipsPosition;
            return animation;
        });

        gltf.userData.vrmAnimations = animations;
    }

    _createNodeMap(defExtension) {
        const humanoidIndexToName = new Map();
        const expressionsIndexToName = new Map();
        let lookAtIndex = null;

        const humanBones = defExtension.humanoid?.humanBones;
        if (humanBones) {
            Object.entries(humanBones).forEach(([name, bone]) => {
                humanoidIndexToName.set(bone.node, name);
            });
        }

        const preset = defExtension.expressions?.preset;
        if (preset) {
            Object.entries(preset).forEach(([name, expression]) => {
                expressionsIndexToName.set(expression.node, name);
            });
        }

        const custom = defExtension.expressions?.custom;
        if (custom) {
            Object.entries(custom).forEach(([name, expression]) => {
                expressionsIndexToName.set(expression.node, name);
            });
        }

        lookAtIndex = defExtension.lookAt?.node ?? null;
        return { humanoidIndexToName, expressionsIndexToName, lookAtIndex };
    }

    async _createBoneWorldMatrixMap(gltf, defExtension) {
        gltf.scene.updateWorldMatrix(false, true);
        const threeNodes = await gltf.parser.getDependencies('node');
        const worldMatrixMap = new Map();

        for (const [boneName, { node }] of Object.entries(defExtension.humanoid.humanBones)) {
            const threeNode = threeNodes[node];
            worldMatrixMap.set(boneName, threeNode.matrixWorld);
            if (boneName === 'hips') {
                worldMatrixMap.set('hipsParent', threeNode.parent?.matrixWorld ?? MAT4_IDENTITY);
            }
        }
        return worldMatrixMap;
    }

    _parseAnimation(animationClip, defAnimation, nodeMap, worldMatrixMap) {
        const tracks = animationClip.tracks;
        const defChannels = defAnimation.channels;
        const result = new VRMAnimation();
        result.duration = animationClip.duration;

        defChannels.forEach((channel, iChannel) => {
            const { node, path } = channel.target;
            const origTrack = tracks[iChannel];
            if (node == null) return;

            
            const boneName = nodeMap.humanoidIndexToName.get(node);
            if (boneName != null) {
                let parentBoneName = VRMHumanBoneParentMap[boneName];
                while (parentBoneName != null && worldMatrixMap.get(parentBoneName) == null) {
                    parentBoneName = VRMHumanBoneParentMap[parentBoneName];
                }
                parentBoneName ??= 'hipsParent';

                if (path === 'translation') {
                    const hipsParentWorldMatrix = worldMatrixMap.get('hipsParent');
                    const trackValues = arrayChunk(origTrack.values, 3).flatMap(v =>
                        _v3A.fromArray(v).applyMatrix4(hipsParentWorldMatrix).toArray()
                    );
                    const track = origTrack.clone();
                    track.values = new Float32Array(trackValues);
                    result.humanoidTracks.translation.set(boneName, track);
                } else if (path === 'rotation') {
                    const worldMatrix = worldMatrixMap.get(boneName);
                    const parentWorldMatrix = worldMatrixMap.get(parentBoneName);
                    _quatA.setFromRotationMatrix(worldMatrix).normalize().invert();
                    _quatB.setFromRotationMatrix(parentWorldMatrix).normalize();
                    const trackValues = arrayChunk(origTrack.values, 4).flatMap(q =>
                        _quatC.fromArray(q).premultiply(_quatB).multiply(_quatA).toArray()
                    );
                    const track = origTrack.clone();
                    track.values = new Float32Array(trackValues);
                    result.humanoidTracks.rotation.set(boneName, track);
                }
                return;
            }

            
            const expressionName = nodeMap.expressionsIndexToName.get(node);
            if (expressionName != null) {
                if (path === 'translation') {
                    const times = origTrack.times;
                    const values = new Float32Array(origTrack.values.length / 3);
                    for (let i = 0; i < values.length; i++) {
                        values[i] = origTrack.values[3 * i];
                    }
                    const newTrack = new THREE.NumberKeyframeTrack(
                        `${expressionName}.weight`, times, values
                    );
                    result.expressionTracks.set(expressionName, newTrack);
                }
                return;
            }

            
            if (node === nodeMap.lookAtIndex) {
                if (path === 'rotation') {
                    result.lookAtTrack = origTrack;
                }
            }
        });

        return result;
    }
}



const _loader = new GLTFLoader();
_loader.register((parser) => new VRMAnimationLoaderPlugin(parser));

export async function loadVRMAnimation(url) {
    const gltf = await _loader.loadAsync(url);
    const vrmAnimations = gltf.userData.vrmAnimations;
    return vrmAnimations?.[0] ?? null;
}
