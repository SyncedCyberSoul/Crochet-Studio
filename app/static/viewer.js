// 3D viewer: photo models (cut-out texture + depth map) and uploaded GLB / STL / OBJ files.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';

const el = document.getElementById('viewer');
const { kind, file, depth, thumbUrl } = el.dataset;
const msg = el.querySelector('.viewer-msg');

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
el.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
camera.position.set(0, 0.1, 3.7);
scene.add(new THREE.HemisphereLight(0xfff6ec, 0x6a5a50, 2.1));
const key = new THREE.DirectionalLight(0xffffff, 2.2);
key.position.set(2, 3, 4);
scene.add(key);
const fill = new THREE.DirectionalLight(0xfff1e6, 0.8); // soft light from the viewer's side
camera.add(fill);
scene.add(camera);
const rim = new THREE.DirectionalLight(0xffe7d6, 0.9);
rim.position.set(-3, 1, -4);
scene.add(rim);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.autoRotate = true;
controls.autoRotateSpeed = 2.2;
controls.minDistance = 1.2;
controls.maxDistance = 12;
controls.saveState();

let front = null;
let back = null;

function resize() {
  const w = el.clientWidth;
  const h = el.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(el);
resize();

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

async function buildPhotoModel() {
  const [texImg, depthImg] = await Promise.all([loadImage(file), loadImage(depth)]);
  const texture = new THREE.Texture(texImg);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  texture.needsUpdate = true;

  const gw = depthImg.naturalWidth;
  const gh = depthImg.naturalHeight;
  const canvas = document.createElement('canvas');
  canvas.width = gw;
  canvas.height = gh;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(depthImg, 0, 0);
  const px = ctx.getImageData(0, 0, gw, gh).data;

  const aspect = texImg.naturalWidth / texImg.naturalHeight;
  const planeW = aspect >= 1 ? 2 : 2 * aspect;
  const planeH = aspect >= 1 ? 2 / aspect : 2;
  const unit = 0.5 * Math.max(planeW, planeH); // matches photo3d.py: 255 = half the long side

  const geometry = new THREE.PlaneGeometry(planeW, planeH, gw - 1, gh - 1);
  const pos = geometry.attributes.position;
  for (let k = 0; k < pos.count; k++) {
    pos.setZ(k, (px[k * 4] / 255) * unit); // PlaneGeometry vertices run row by row from the top, like the image
  }
  geometry.computeVertexNormals();

  const material = new THREE.MeshStandardMaterial({ map: texture, alphaTest: 0.5, roughness: 0.92, metalness: 0 });
  front = new THREE.Mesh(geometry, material);
  // The back: same outline, a little flatter and darker (we only have a photo of the front).
  back = new THREE.Mesh(geometry, material.clone());
  back.material.color = new THREE.Color(0.78, 0.76, 0.74);
  back.scale.z = -0.8;
  const group = new THREE.Group();
  group.add(front, back);
  // Centre and size the view on the piece itself, not the whole photo it was cut from.
  let x0 = gw, x1 = -1, y0 = gh, y1 = -1;
  for (let k = 0; k < gw * gh; k++) {
    if (px[k * 4] > 2) {
      const x = k % gw, y = Math.floor(k / gw);
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
    }
  }
  if (x1 >= x0) {
    const cx = ((x0 + x1) / 2 / (gw - 1) - 0.5) * planeW;
    const cy = (0.5 - (y0 + y1) / 2 / (gh - 1)) * planeH;
    const span = Math.max(((x1 - x0) / (gw - 1)) * planeW, ((y1 - y0) / (gh - 1)) * planeH);
    const s = 2 / Math.max(span, 0.2);
    group.scale.setScalar(s);
    group.position.set(-cx * s, -cy * s, 0);
  }
  scene.add(group);
}

function fit(object) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const scale = 2.2 / Math.max(size.x, size.y, size.z || 1e-6);
  object.position.sub(center.multiplyScalar(scale));
  object.scale.setScalar(scale);
}

const yarnMaterial = () => new THREE.MeshStandardMaterial({ color: 0xc4694b, roughness: 0.85 });

async function buildFileModel() {
  let object;
  if (kind === 'glb') {
    object = (await new GLTFLoader().loadAsync(file)).scene;
  } else if (kind === 'stl') {
    const geometry = await new STLLoader().loadAsync(file);
    geometry.computeVertexNormals();
    object = new THREE.Mesh(geometry, yarnMaterial());
    object.rotation.x = -Math.PI / 2; // STL files are usually Z-up
  } else {
    object = await new OBJLoader().loadAsync(file);
    object.traverse((child) => { if (child.isMesh && !child.material?.map) child.material = yarnMaterial(); });
  }
  const holder = new THREE.Group();
  holder.add(object);
  fit(holder);
  scene.add(holder);
}

function snapshotOnce() {
  if (!thumbUrl) return;
  setTimeout(() => {
    const image = renderer.domElement.toDataURL('image/png');
    fetch(thumbUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image }) });
  }, 1200);
}

(async () => {
  try {
    await (kind === 'photo' ? buildPhotoModel() : buildFileModel());
    msg.remove();
    snapshotOnce();
  } catch (e) {
    console.error(e);
    msg.textContent = "Couldn't open this 3D model.";
  }
})();

renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});

document.querySelector('[data-action="spin"]')?.addEventListener('click', (e) => {
  controls.autoRotate = !controls.autoRotate;
  e.currentTarget.setAttribute('aria-pressed', String(controls.autoRotate));
});
document.querySelector('[data-action="reset"]')?.addEventListener('click', () => controls.reset());
document.querySelector('[data-action="puff"]')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  if (front) front.scale.z = v;
  if (back) back.scale.z = -0.8 * v;
});
