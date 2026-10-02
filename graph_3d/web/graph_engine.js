/**
 * graph_engine.js
 * FinMind 3D Knowledge Universe - Apple Pro Matte GPU Engine
 * Folyamatos, hipnotikus galaktikus keringés, letisztult dizájn,
 * és dinamikus "csillagszületés" animáció (Shockwave & Lerp) az új tanulmányok beérkezésekor!
 */

class GraphEngine3D {
  constructor(containerId, options = {}) {
    this.container = document.getElementById(containerId);
    if (!this.container) throw new Error(`Container #${containerId} nem található`);

    this.options = Object.assign({
      autoRotate: true,
      autoRotateSpeed: 0.35,
      linkOpacity: 0.18,
      backgroundColor: 0x121214 // Apple Pro Dark Matte
    }, options);

    // Belső adatreprezentáció
    this.nodes = [];
    this.links = [];
    this.nodeIndexMap = new Map();
    this.adjacency = new Map();

    // Hover & kiválasztás
    this.hoveredNodeId = null;

    // Callbacks
    this.onNodeHover = null;
    this.onFpsUpdate = null;

    // Three.js elemek
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.controls = null;
    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2(-9999, -9999);

    // Geometriák és Meshek
    this.instancedMesh = null;
    this.linkSegments = null;
    this.starfield = null;

    // Mátrixok és színek
    this.dummyMatrix = new THREE.Matrix4();
    this.dummyPosition = new THREE.Vector3();
    this.dummyScale = new THREE.Vector3();
    this.dummyColor = new THREE.Color();
    this.baseColors = [];
    this.baseScales = [];

    // Dinamikus animációk listája (új csomópontok érkezésekor)
    this.activeSpawns = []; // { nodeIndex, startPos, targetPos, startTime, duration, targetScale }
    this.activeShockwaves = []; // { mesh, startTime, duration }

    // Teljesítmény mérés (FPS)
    this.lastTime = performance.now();
    this.frameCount = 0;
    this.currentFps = 60;

    this.initScene();
    this.initEvents();
    this.animate = this.animate.bind(this);
    requestAnimationFrame(this.animate);
  }

  initScene() {
    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;

    // 1. Scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(this.options.backgroundColor);
    this.scene.fog = new THREE.FogExp2(this.options.backgroundColor, 0.00035);

    // 2. Camera
    this.camera = new THREE.PerspectiveCamera(48, width / height, 1, 10000);
    this.camera.position.set(0, 320, 1150);

    // 3. WebGL Renderer
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: "high-performance",
      stencil: false
    });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.container.appendChild(this.renderer.domElement);

    // 4. Orbit Controls (Sima, folyamatos galaktikus keringés)
    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.screenSpacePanning = true;
    this.controls.minDistance = 60;
    this.controls.maxDistance = 4000;
    this.controls.autoRotate = this.options.autoRotate;
    this.controls.autoRotateSpeed = this.options.autoRotateSpeed;

    // 5. Megvilágítás (Letisztult, finom Apple stílusú lágy fények)
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
    this.scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.7);
    dirLight1.position.set(400, 700, 500);
    this.scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x0a84ff, 0.4);
    dirLight2.position.set(-400, -500, -400);
    this.scene.add(dirLight2);

    // 6. Finom háttér por / csillagmező
    this.initStarfield();
  }

  initStarfield() {
    const count = 1800;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);

    for (let i = 0; i < count; i++) {
      const radius = 1600 + Math.random() * 2000;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);

      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = radius * Math.cos(phi);

      const shade = 0.4 + Math.random() * 0.4;
      colors[i * 3] = shade;
      colors[i * 3 + 1] = shade;
      colors[i * 3 + 2] = shade * 1.1;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size: 2.0,
      vertexColors: true,
      transparent: true,
      opacity: 0.5,
      fog: false
    });

    this.starfield = new THREE.Points(geometry, material);
    this.scene.add(this.starfield);
  }

  // ─── Adatfrissítés & GPU Instancing ──────────────────────────

  setGraphData(graphData, newlyArrivedNodeIds = []) {
    const oldNodeIds = new Set(this.nodes.map(n => n.id));
    this.nodes = graphData.nodes || [];
    this.links = graphData.links || [];

    this.nodeIndexMap.clear();
    this.adjacency.clear();

    for (let i = 0; i < this.nodes.length; i++) {
      const n = this.nodes[i];
      this.nodeIndexMap.set(n.id, i);
      this.adjacency.set(n.id, new Set());
    }

    for (let l of this.links) {
      const srcId = typeof l.source === 'object' ? l.source.id : l.source;
      const tgtId = typeof l.target === 'object' ? l.target.id : l.target;
      if (this.adjacency.has(srcId)) this.adjacency.get(srcId).add(tgtId);
      if (this.adjacency.has(tgtId)) this.adjacency.get(tgtId).add(srcId);
    }

    // Új csomópontok azonosítása
    const incomingIds = newlyArrivedNodeIds.length > 0
      ? newlyArrivedNodeIds
      : this.nodes.filter(n => !oldNodeIds.has(n.id) && oldNodeIds.size > 0).map(n => n.id);

    this.rebuildNodeMesh(incomingIds);
    this.rebuildLinkMesh();
  }

  rebuildNodeMesh(incomingIds = []) {
    if (this.instancedMesh) {
      this.scene.remove(this.instancedMesh);
      this.instancedMesh.geometry.dispose();
      this.instancedMesh.material.dispose();
      this.instancedMesh = null;
    }

    const count = this.nodes.length;
    if (count === 0) return;

    // Selymes, letisztult Apple gömb geometria
    const geometry = new THREE.SphereGeometry(1, 14, 14);
    const material = new THREE.MeshStandardMaterial({
      roughness: 0.4,
      metalness: 0.15
    });

    this.instancedMesh = new THREE.InstancedMesh(geometry, material, count);
    this.instancedMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.instancedMesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3);

    this.baseColors = new Array(count);
    this.baseScales = new Array(count);

    const incomingSet = new Set(incomingIds);

    for (let i = 0; i < count; i++) {
      const n = this.nodes[i];
      const x = n.x || 0;
      const y = n.y || 0;
      const z = n.z || 0;

      // Méretezés
      let scale = n.val || 5.0;
      if (n.type === 'discipline') scale = Math.max(scale, 13.0);
      else if (n.type === 'strategy') scale = Math.max(scale, 8.5);
      else if (n.type === 'author') scale = Math.max(scale, 5.5);
      else scale = Math.max(scale, 3.2);

      this.baseScales[i] = scale;

      const isNew = incomingSet.has(n.id);
      if (isNew) {
        // Új csomópont: külső űrből sodródik be
        const startPos = new THREE.Vector3(x * 1.35, y + 140, z * 1.35);
        this.dummyMatrix.makeScale(0.01, 0.01, 0.01);
        this.dummyMatrix.setPosition(startPos.x, startPos.y, startPos.z);
        this.instancedMesh.setMatrixAt(i, this.dummyMatrix);

        // Becsatolás az aktív animációk közé
        this.activeSpawns.push({
          nodeIndex: i,
          startPos: startPos,
          targetPos: new THREE.Vector3(x, y, z),
          startTime: performance.now(),
          duration: 1600, // 1.6 mp sima lerp
          targetScale: scale
        });

        // Hozzuk létre a táguló sokkhullám karikát (Shockwave Ring Effect)
        this.createShockwave(new THREE.Vector3(x, y, z), n.color || 0x30d158);
      } else {
        this.dummyMatrix.makeScale(scale, scale, scale);
        this.dummyMatrix.setPosition(x, y, z);
        this.instancedMesh.setMatrixAt(i, this.dummyMatrix);
      }

      // Szín hozzárendelés
      const colHex = n.color || '#0A84FF';
      const col = new THREE.Color(colHex);
      this.baseColors[i] = col;
      this.instancedMesh.setColorAt(i, col);
    }

    this.instancedMesh.instanceMatrix.needsUpdate = true;
    if (this.instancedMesh.instanceColor) {
      this.instancedMesh.instanceColor.needsUpdate = true;
    }

    this.scene.add(this.instancedMesh);
  }

  createShockwave(position, colorHex) {
    const ringGeo = new THREE.RingGeometry(1.5, 3.5, 32);
    const ringMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(colorHex),
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });

    const ringMesh = new THREE.Mesh(ringGeo, ringMat);
    ringMesh.position.copy(position);
    ringMesh.lookAt(this.camera.position);

    this.scene.add(ringMesh);

    this.activeShockwaves.push({
      mesh: ringMesh,
      startTime: performance.now(),
      duration: 1400
    });
  }

  rebuildLinkMesh() {
    if (this.linkSegments) {
      this.scene.remove(this.linkSegments);
      this.linkSegments.geometry.dispose();
      this.linkSegments.material.dispose();
      this.linkSegments = null;
    }

    const validLinks = [];
    for (let link of this.links) {
      const srcId = typeof link.source === 'object' ? link.source.id : link.source;
      const tgtId = typeof link.target === 'object' ? link.target.id : link.target;
      if (this.nodeIndexMap.has(srcId) && this.nodeIndexMap.has(tgtId)) {
        validLinks.push({ srcIdx: this.nodeIndexMap.get(srcId), tgtIdx: this.nodeIndexMap.get(tgtId) });
      }
    }

    const count = validLinks.length;
    if (count === 0) return;

    const positions = new Float32Array(count * 6);
    const colors = new Float32Array(count * 6);

    for (let i = 0; i < count; i++) {
      const l = validLinks[i];
      const sNode = this.nodes[l.srcIdx];
      const tNode = this.nodes[l.tgtIdx];

      positions[i * 6] = sNode.x || 0;
      positions[i * 6 + 1] = sNode.y || 0;
      positions[i * 6 + 2] = sNode.z || 0;

      positions[i * 6 + 3] = tNode.x || 0;
      positions[i * 6 + 4] = tNode.y || 0;
      positions[i * 6 + 5] = tNode.z || 0;

      // Finom letisztult áttetsző vonalszínek
      const c1 = this.baseColors[l.srcIdx] || new THREE.Color(0xa1a1a6);
      const c2 = this.baseColors[l.tgtIdx] || new THREE.Color(0xa1a1a6);

      colors[i * 6] = c1.r * 0.45;
      colors[i * 6 + 1] = c1.g * 0.45;
      colors[i * 6 + 2] = c1.b * 0.45;

      colors[i * 6 + 3] = c2.r * 0.45;
      colors[i * 6 + 4] = c2.g * 0.45;
      colors[i * 6 + 5] = c2.b * 0.45;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: this.options.linkOpacity,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });

    this.linkSegments = new THREE.LineSegments(geometry, material);
    this.scene.add(this.linkSegments);
  }

  // ─── Kamera Reset & Forgatás ──────────────────────────────────

  resetCamera() {
    this.camera.position.set(0, 320, 1150);
    this.controls.target.set(0, 0, 0);
  }

  toggleAutoRotate(enable) {
    this.options.autoRotate = enable;
    this.controls.autoRotate = enable;
  }

  // ─── Események ───────────────────────────────────────────────

  initEvents() {
    window.addEventListener('resize', this.onWindowResize.bind(this));

    this.container.addEventListener('mousemove', (e) => {
      const rect = this.container.getBoundingClientRect();
      this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    });

    window.addEventListener('keydown', (e) => {
      if (e.code === 'KeyR') this.resetCamera();
    });
  }

  onWindowResize() {
    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;

    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  // ─── Fő Renderelési Ciklus (60 FPS) ───────────────────────────

  animate(time) {
    requestAnimationFrame(this.animate);

    const delta = (time - this.lastTime) / 1000.0;
    this.lastTime = time;

    // FPS Számláló
    this.frameCount++;
    if (this.frameCount % 20 === 0) {
      this.currentFps = Math.round(1.0 / Math.max(delta, 0.001));
      if (typeof this.onFpsUpdate === 'function') {
        this.onFpsUpdate(this.currentFps);
      }
    }

    // 1. Új Csomópontok Születési & Repülési Animációja (Lerp + Bloom)
    if (this.activeSpawns.length > 0 && this.instancedMesh) {
      const now = performance.now();
      for (let j = this.activeSpawns.length - 1; j >= 0; j--) {
        const anim = this.activeSpawns[j];
        const progress = Math.min((now - anim.startTime) / anim.duration, 1.0);

        // Smooth cubic ease-out
        const ease = 1 - Math.pow(1 - progress, 3);

        // Pozíció lerp a kiindulási ponttól a végleges helyére
        this.dummyPosition.lerpVectors(anim.startPos, anim.targetPos, ease);

        // Skála pulzálás (kinyílik, kissé túlnyúlik, majd a helyére ugrik)
        const scaleOvershoot = 1.0 + 0.3 * Math.sin(progress * Math.PI);
        const curScale = anim.targetScale * ease * scaleOvershoot;
        this.dummyScale.set(curScale, curScale, curScale);

        this.dummyMatrix.makeScale(curScale, curScale, curScale);
        this.dummyMatrix.setPosition(this.dummyPosition.x, this.dummyPosition.y, this.dummyPosition.z);
        this.instancedMesh.setMatrixAt(anim.nodeIndex, this.dummyMatrix);

        if (progress >= 1.0) {
          this.activeSpawns.splice(j, 1);
        }
      }
      this.instancedMesh.instanceMatrix.needsUpdate = true;
    }

    // 2. Sokkhullámok (Shockwaves) tágulása és elhalványulása
    if (this.activeShockwaves.length > 0) {
      const now = performance.now();
      for (let k = this.activeShockwaves.length - 1; k >= 0; k--) {
        const sw = this.activeShockwaves[k];
        const p = Math.min((now - sw.startTime) / sw.duration, 1.0);

        const scale = 1.0 + p * 12.0;
        sw.mesh.scale.set(scale, scale, scale);
        sw.mesh.material.opacity = (1.0 - p) * 0.8;
        sw.mesh.lookAt(this.camera.position);

        if (p >= 1.0) {
          this.scene.remove(sw.mesh);
          sw.mesh.geometry.dispose();
          sw.mesh.material.dispose();
          this.activeShockwaves.splice(k, 1);
        }
      }
    }

    // Keringés frissítés
    this.controls.update();

    // Háttér csillagmező lassan forog
    if (this.starfield) {
      this.starfield.rotation.y += 0.0001;
    }

    // Raycast hover detektálás (csak minden 2. képkockán a GPU tehermentesítéséért)
    if (this.frameCount % 2 === 0 && this.instancedMesh) {
      this.raycaster.setFromCamera(this.mouse, this.camera);
      const intersects = this.raycaster.intersectObject(this.instancedMesh);

      if (intersects.length > 0) {
        const instanceId = intersects[0].instanceId;
        if (instanceId !== undefined && instanceId < this.nodes.length) {
          const hoveredNode = this.nodes[instanceId];
          if (this.hoveredNodeId !== hoveredNode.id) {
            this.hoveredNodeId = hoveredNode.id;
            this.container.style.cursor = 'pointer';
            if (typeof this.onNodeHover === 'function') {
              this.onNodeHover(hoveredNode, intersects[0]);
            }
          }
        }
      } else {
        if (this.hoveredNodeId !== null) {
          this.hoveredNodeId = null;
          this.container.style.cursor = 'default';
          if (typeof this.onNodeHover === 'function') {
            this.onNodeHover(null, null);
          }
        }
      }
    }

    this.renderer.render(this.scene, this.camera);
  }
}

window.GraphEngine3D = GraphEngine3D;
