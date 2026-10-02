/**
 * graph_engine.js
 * FinMind 3D Knowledge Universe - Apple Pro Matte GPU Engine
 * Folyamatos, hipnotikus galaktikus keringés, letisztult dizájn,
 * és dinamikus "csillagszületés" animáció (Shockwave & Lerp) az új tanulmányok beérkezésekor!
 */

// ─── Választható Színpaletták Gyűjteménye ─────────────────────────
const COLOR_PALETTES = {
  cyber: {
    id: 'cyber',
    name: 'Apple Cyber',
    disciplines: {
      QuantitativeFinance: '#0A84FF',
      EconomicsAndEconometrics: '#30D158',
      ComputerScienceAndAI: '#64D2FF',
      MathematicsAndStatistics: '#BF5AF2',
      PhysicsAndComplexSystems: '#FF9F0A',
      AstrophysicsAndCosmology: '#30D158',
      InterdisciplinaryScience: '#5E5CE6',
      Other: '#98989D'
    },
    types: {
      paper: '#0A84FF',
      author: '#FF9F0A',
      strategy: '#FF453A',
      discipline: '#30D158',
      asset: '#BF5AF2',
      topic: '#6E6E73'
    },
    accent: '#30D158',
    lineColor: '#6E6E73'
  },
  monochrome: {
    id: 'monochrome',
    name: 'Monochrome Minimal',
    disciplines: {
      QuantitativeFinance: '#FFFFFF',
      EconomicsAndEconometrics: '#E5E5EA',
      ComputerScienceAndAI: '#D1D1D6',
      MathematicsAndStatistics: '#C7C7CC',
      PhysicsAndComplexSystems: '#AEAEB2',
      AstrophysicsAndCosmology: '#8E8E93',
      InterdisciplinaryScience: '#E5E5EA',
      Other: '#636366'
    },
    types: {
      paper: '#FFFFFF',
      author: '#D1D1D6',
      strategy: '#E5E5EA',
      discipline: '#FFFFFF',
      asset: '#AEAEB2',
      topic: '#636366'
    },
    accent: '#FFFFFF',
    lineColor: '#48484A'
  },
  emerald: {
    id: 'emerald',
    name: 'Deep Emerald',
    disciplines: {
      QuantitativeFinance: '#00F5D4',
      EconomicsAndEconometrics: '#30D158',
      ComputerScienceAndAI: '#00BBF9',
      MathematicsAndStatistics: '#2EC4B6',
      PhysicsAndComplexSystems: '#20BF6B',
      AstrophysicsAndCosmology: '#52B788',
      InterdisciplinaryScience: '#38B000',
      Other: '#40916C'
    },
    types: {
      paper: '#00F5D4',
      author: '#52B788',
      strategy: '#30D158',
      discipline: '#20BF6B',
      asset: '#00BBF9',
      topic: '#2EC4B6'
    },
    accent: '#00F5D4',
    lineColor: '#1B4332'
  },
  solar: {
    id: 'solar',
    name: 'Solar Amber',
    disciplines: {
      QuantitativeFinance: '#FFD166',
      EconomicsAndEconometrics: '#FFB703',
      ComputerScienceAndAI: '#FB8500',
      MathematicsAndStatistics: '#FF9F0A',
      PhysicsAndComplexSystems: '#FF5400',
      AstrophysicsAndCosmology: '#F77F00',
      InterdisciplinaryScience: '#E85D04',
      Other: '#D90429'
    },
    types: {
      paper: '#FFD166',
      author: '#FFB703',
      strategy: '#FF5400',
      discipline: '#FB8500',
      asset: '#F77F00',
      topic: '#D90429'
    },
    accent: '#FFD166',
    lineColor: '#6A040F'
  },
  nebula: {
    id: 'nebula',
    name: 'Nebula Violet',
    disciplines: {
      QuantitativeFinance: '#BF5AF2',
      EconomicsAndEconometrics: '#5E5CE6',
      ComputerScienceAndAI: '#64D2FF',
      MathematicsAndStatistics: '#DA70D6',
      PhysicsAndComplexSystems: '#E0AAFF',
      AstrophysicsAndCosmology: '#9D4EDD',
      InterdisciplinaryScience: '#7B2CBF',
      Other: '#5A189A'
    },
    types: {
      paper: '#BF5AF2',
      author: '#E0AAFF',
      strategy: '#FF2A85',
      discipline: '#64D2FF',
      asset: '#9D4EDD',
      topic: '#5A189A'
    },
    accent: '#BF5AF2',
    lineColor: '#3C096C'
  }
};

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

    // Színpaletta állapot (perzisztált választás)
    let savedPal = 'cyber';
    try {
      savedPal = localStorage.getItem('finmind_palette_3d') || 'cyber';
    } catch (e) {}
    this.activePaletteId = COLOR_PALETTES[savedPal] ? savedPal : 'cyber';

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
    this.scene.fog = new THREE.FogExp2(this.options.backgroundColor, 0.00016);

    // 2. Camera (Tágas, szellős 3D látótér)
    this.camera = new THREE.PerspectiveCamera(48, width / height, 1, 15000);
    this.camera.position.set(0, 480, 2200);

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
    this.controls.maxDistance = 8000;
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

    // 6. Letisztult Apple Dark Matte háttér (háttér csillagok nélkül)
  }

  // ─── Színpaletta Kezelés ──────────────────────────────────────

  getNodeColor(node) {
    const pal = COLOR_PALETTES[this.activePaletteId] || COLOR_PALETTES['cyber'];
    if (node.type === 'discipline') {
      const disc = node.label || node.primary_discipline;
      if (pal.disciplines && pal.disciplines[disc]) return pal.disciplines[disc];
    }
    if (node.type === 'paper' && node.primary_discipline && pal.disciplines && pal.disciplines[node.primary_discipline]) {
      return pal.disciplines[node.primary_discipline];
    }
    if (pal.types && pal.types[node.type]) {
      return pal.types[node.type];
    }
    return node.color || pal.accent || '#0A84FF';
  }

  setColorPalette(paletteId) {
    if (!COLOR_PALETTES[paletteId]) return;
    this.activePaletteId = paletteId;
    try {
      localStorage.setItem('finmind_palette_3d', paletteId);
    } catch (e) {}

    const count = this.nodes.length;
    for (let i = 0; i < count; i++) {
      const colHex = this.getNodeColor(this.nodes[i]);
      this.baseColors[i] = new THREE.Color(colHex);
      if (this.instancedMesh) {
        this.instancedMesh.setColorAt(i, this.baseColors[i]);
      }
    }

    if (this.instancedMesh && this.instancedMesh.instanceColor) {
      this.instancedMesh.instanceColor.needsUpdate = true;
    }

    this.rebuildLinkMesh();
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

    // Ha érkezett új csomópont és ez nem a kezdeti betöltés:
    // Elindítjuk az elsötétülős, végigsöprő sokkhullám animációt!
    if (incomingIds.length > 0 && oldNodeIds.size > 0) {
      const incomingSet = new Set(incomingIds);
      const firstNew = this.nodes.find(n => incomingSet.has(n.id));
      if (firstNew) {
        const originPos = new THREE.Vector3(firstNew.x || 0, firstNew.y || 0, firstNew.z || 0);
        this.triggerArrivalShockwave(originPos, incomingIds);
      }
    }
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
        // Új csomópont: külső űrből sodródik be lágyan
        const startPos = new THREE.Vector3(x * 1.35, y + 140, z * 1.35);
        this.dummyMatrix.makeScale(0.01, 0.01, 0.01);
        this.dummyMatrix.setPosition(startPos.x, startPos.y, startPos.z);
        this.instancedMesh.setMatrixAt(i, this.dummyMatrix);

        this.activeSpawns.push({
          nodeIndex: i,
          startPos: startPos,
          targetPos: new THREE.Vector3(x, y, z),
          startTime: performance.now(),
          duration: 1600,
          targetScale: scale
        });
      } else {
        this.dummyMatrix.makeScale(scale, scale, scale);
        this.dummyMatrix.setPosition(x, y, z);
        this.instancedMesh.setMatrixAt(i, this.dummyMatrix);
      }

      // Szín hozzárendelés az aktív paletta alapján
      const colHex = this.getNodeColor(n);
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

  // ─── Látványos Elsötétülő & Hullámszerűen Visszaszínező Shockwave ──

  triggerArrivalShockwave(originPos, incomingIds = []) {
    const count = this.nodes.length;
    if (count === 0 || !this.instancedMesh) return;

    const pal = COLOR_PALETTES[this.activePaletteId] || COLOR_PALETTES['cyber'];
    const accentCol = new THREE.Color(pal.accent || '#30D158');

    // 1. Távolságok kiszámítása az epicentrumtól
    const distances = new Float32Array(count);
    let maxDist = 0;
    for (let i = 0; i < count; i++) {
      const n = this.nodes[i];
      const dx = (n.x || 0) - originPos.x;
      const dy = (n.y || 0) - originPos.y;
      const dz = (n.z || 0) - originPos.z;
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
      distances[i] = d;
      if (d > maxDist) maxDist = d;
    }
    const maxR = Math.max(maxDist + 400, 3800);
    const newIdSet = new Set(incomingIds);

    // 2. Minden korábbi pont azonnal elsötétül, KIVÉVE az új csomópont(ok)at!
    const darkCol = new THREE.Color();
    for (let i = 0; i < count; i++) {
      if (newIdSet.has(this.nodes[i].id)) {
        // Az új elem megőrzi teljes élénk színét
        this.instancedMesh.setColorAt(i, this.baseColors[i]);
      } else {
        // Minden meglévő csomópont elsötétül mély parázs-szintre
        darkCol.copy(this.baseColors[i]).multiplyScalar(0.06);
        this.instancedMesh.setColorAt(i, darkCol);
      }
    }
    this.instancedMesh.instanceColor.needsUpdate = true;

    // 3. Halványítjuk az éleket a sokkhullám végigsöprése alatt
    if (this.linkSegments && this.linkSegments.material) {
      this.linkSegments.material.opacity = this.options.linkOpacity * 0.15;
    }

    // 4. Látványos 3D Sokkhullám Gyűrűk
    const ringGeo = new THREE.RingGeometry(8.0, 24.0, 64);
    const ringMat = new THREE.MeshBasicMaterial({
      color: accentCol,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    const ringMesh = new THREE.Mesh(ringGeo, ringMat);
    ringMesh.position.copy(originPos);
    ringMesh.lookAt(this.camera.position);
    this.scene.add(ringMesh);

    const innerRingGeo = new THREE.RingGeometry(3.0, 10.0, 48);
    const innerRingMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(1, 1, 1),
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.9,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    const innerRingMesh = new THREE.Mesh(innerRingGeo, innerRingMat);
    innerRingMesh.position.copy(originPos);
    innerRingMesh.lookAt(this.camera.position);
    this.scene.add(innerRingMesh);

    this.activeShockwaves.push({
      mesh: ringMesh,
      innerMesh: innerRingMesh,
      origin: originPos.clone(),
      startTime: performance.now(),
      duration: 2500, // 2.5 másodperces sima söprés
      maxRadius: maxR,
      waveWidth: 260,
      distances: distances,
      newIdSet: newIdSet,
      isAwakening: true
    });
  }

  testShockwave() {
    if (!this.nodes || this.nodes.length === 0) return;
    const papers = this.nodes.filter(n => n.type === 'paper');
    const target = papers.length > 0
      ? papers[Math.floor(Math.random() * papers.length)]
      : this.nodes[Math.floor(Math.random() * this.nodes.length)];
    const pos = new THREE.Vector3(target.x || 0, target.y || 0, target.z || 0);
    this.triggerArrivalShockwave(pos, [target.id]);
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
    this.camera.position.set(0, 480, 2200);
    this.controls.target.set(0, 0, 0);
    this.controls.update();
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

    // 2. Sokkhullámok (Shockwaves) tágulása és a pontok sorban való visszaszínezése
    if (this.activeShockwaves.length > 0) {
      const now = performance.now();
      const whiteCol = new THREE.Color(1, 1, 1);
      const tempCol = new THREE.Color();

      for (let k = this.activeShockwaves.length - 1; k >= 0; k--) {
        const sw = this.activeShockwaves[k];
        const progress = Math.min((now - sw.startTime) / sw.duration, 1.0);

        // Sima cubic ease-out a hullám terjedési sebességére
        const ease = 1 - Math.pow(1 - progress, 3);
        const currentR = sw.maxRadius * ease;

        // Vizuális gyűrűk tágulása és halványulása
        if (sw.mesh) {
          const s = Math.max(currentR / 12.0, 0.1);
          sw.mesh.scale.set(s, s, s);
          sw.mesh.material.opacity = (1.0 - progress) * 0.95;
          sw.mesh.lookAt(this.camera.position);
        }
        if (sw.innerMesh) {
          const sIn = Math.max(currentR / 8.0, 0.1);
          sw.innerMesh.scale.set(sIn, sIn, sIn);
          sw.innerMesh.material.opacity = (1.0 - progress) * 0.85;
          sw.innerMesh.lookAt(this.camera.position);
        }

        // Csomópontok visszaszínezése a hullámfront terjedésével
        if (sw.isAwakening && this.instancedMesh) {
          const waveW = sw.waveWidth;
          const nodeCount = this.nodes.length;

          for (let i = 0; i < nodeCount; i++) {
            if (sw.newIdSet && sw.newIdSet.has(this.nodes[i].id)) {
              // Az új elem megőrzi teljes élénk színét
              continue;
            }

            const d = sw.distances[i];
            if (d > currentR) {
              // A hullám még nem érte el: mély sötétben marad
              tempCol.copy(this.baseColors[i]).multiplyScalar(0.06);
              this.instancedMesh.setColorAt(i, tempCol);
            } else if (d >= currentR - waveW) {
              // Pontosan a hullámfrontban van: fénylő energialöket / villanás!
              const waveProgress = (d - (currentR - waveW)) / waveW; // 0..1
              const pulse = Math.sin(waveProgress * Math.PI);
              tempCol.copy(this.baseColors[i]).lerp(whiteCol, 0.65 * pulse).multiplyScalar(1.0 + 1.2 * pulse);
              this.instancedMesh.setColorAt(i, tempCol);
            } else {
              // A hullám már áthaladt: visszanyerte a teljes eredeti paletta színét!
              this.instancedMesh.setColorAt(i, this.baseColors[i]);
            }
          }
          this.instancedMesh.instanceColor.needsUpdate = true;
        }

        if (progress >= 1.0) {
          // Takarítás a hullám lecsengésekor
          if (sw.mesh) {
            this.scene.remove(sw.mesh);
            sw.mesh.geometry.dispose();
            sw.mesh.material.dispose();
          }
          if (sw.innerMesh) {
            this.scene.remove(sw.innerMesh);
            sw.innerMesh.geometry.dispose();
            sw.innerMesh.material.dispose();
          }
          // Biztosítjuk, hogy minden pont pontosan visszakapja a bázisszínét
          for (let i = 0; i < this.nodes.length; i++) {
            this.instancedMesh.setColorAt(i, this.baseColors[i]);
          }
          this.instancedMesh.instanceColor.needsUpdate = true;

          // Visszaállítjuk az élek átlátszóságát
          if (this.linkSegments && this.linkSegments.material) {
            this.linkSegments.material.opacity = this.options.linkOpacity;
          }

          this.activeShockwaves.splice(k, 1);
        }
      }
    }

    // Keringés frissítés (folyamatos, sima galaktikus forgás)
    this.controls.update();

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
