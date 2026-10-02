/**
 * graph_engine.js
 * Nagy teljesítményű 3D WebGL Gráf Megjelenítő Motor (Three.js GPU Instancing).
 * Képes 10 000 - 50 000+ csomópontot és százezer élt kirajzolni 60 FPS sebességgel,
 * mindössze 2 Draw Call segítségével (InstancedMesh a pontokhoz, LineSegments az élekhez).
 */

class GraphEngine3D {
  constructor(containerId, options = {}) {
    this.container = document.getElementById(containerId);
    if (!this.container) throw new Error(`Container #${containerId} nem található`);

    this.options = Object.assign({
      bloomEnabled: true,
      starfieldEnabled: true,
      autoRotate: false,
      linkOpacity: 0.4,
      colorMode: 'discipline'
    }, options);

    // Belső adatreprezentáció
    this.nodes = [];
    this.links = [];
    this.nodeIndexMap = new Map(); // id -> index
    this.adjacency = new Map();    // id -> Set of neighbor ids

    // Kiválasztási és hover állapot
    this.hoveredNodeId = null;
    this.selectedNodeId = null;
    this.isolatedNodeId = null;

    // Callbacks
    this.onNodeClick = null;
    this.onNodeHover = null;
    this.onFpsUpdate = null;

    // Three.js elemek
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.controls = null;
    this.composer = null;
    this.bloomPass = null;
    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2(-9999, -9999);

    // Geometriák és Meshek
    this.instancedMesh = null;
    this.linkSegments = null;
    this.starfield = null;

    // Színkezelés
    this.dummyMatrix = new THREE.Matrix4();
    this.dummyColor = new THREE.Color();
    this.baseColors = []; // Float32Array vagy Color objektumok

    // Kamera animáció állapot (FlyTo)
    this.cameraAnimation = null;

    // Billentyűzet navigáció
    this.keysDown = {};

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
    this.scene.background = new THREE.Color(0x030712); // Deep cosmic void
    this.scene.fog = new THREE.FogExp2(0x030712, 0.0004);

    // 2. Camera
    this.camera = new THREE.PerspectiveCamera(50, width / height, 1, 10000);
    this.camera.position.set(0, 350, 1100);

    // 3. WebGL Renderer
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: "high-performance",
      stencil: false
    });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.1;
    this.container.appendChild(this.renderer.domElement);

    // 4. Orbit Controls
    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.screenSpacePanning = true;
    this.controls.minDistance = 20;
    this.controls.maxDistance = 4500;
    this.controls.autoRotate = this.options.autoRotate;
    this.controls.autoRotateSpeed = 0.6;

    // 5. Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    this.scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0x00f3ff, 0.8);
    dirLight1.position.set(500, 800, 500);
    this.scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0xa855f7, 0.6);
    dirLight2.position.set(-500, -800, -500);
    this.scene.add(dirLight2);

    // 6. Post-Processing (UnrealBloomPass Neon Glow)
    this.initPostProcessing(width, height);

    // 7. Starfield Background
    if (this.options.starfieldEnabled) {
      this.initStarfield();
    }
  }

  initPostProcessing(width, height) {
    try {
      if (typeof THREE.EffectComposer !== 'undefined' && typeof THREE.UnrealBloomPass !== 'undefined') {
        const renderPass = new THREE.RenderPass(this.scene, this.camera);
        
        // Neon Bloom beállítások
        this.bloomPass = new THREE.UnrealBloomPass(
          new THREE.Vector2(width, height),
          1.1,  // Strength
          0.6,  // Radius
          0.15  // Threshold
        );

        this.composer = new THREE.EffectComposer(this.renderer);
        this.composer.addPass(renderPass);
        this.composer.addPass(this.bloomPass);
      }
    } catch (e) {
      console.warn("Bloom post-processing nem inicializálható, fallback sima rendererre:", e);
      this.composer = null;
    }
  }

  initStarfield() {
    const starCount = 3000;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(starCount * 3);
    const colors = new Float32Array(starCount * 3);

    for (let i = 0; i < starCount; i++) {
      const radius = 1800 + Math.random() * 2200;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);

      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = radius * Math.cos(phi);

      // Enyhe kékesszürke és lila csillag színek
      const shade = 0.5 + Math.random() * 0.5;
      colors[i * 3] = shade * 0.7;
      colors[i * 3 + 1] = shade * 0.9;
      colors[i * 3 + 2] = shade;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size: 2.5,
      vertexColors: true,
      transparent: true,
      opacity: 0.7,
      fog: false
    });

    this.starfield = new THREE.Points(geometry, material);
    this.scene.add(this.starfield);
  }

  // ─── Gráf Adatok Betöltése & GPU Instancing ───────────────────

  setGraphData(graphData) {
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

    this.rebuildNodeMesh();
    this.rebuildLinkMesh();
  }

  rebuildNodeMesh() {
    if (this.instancedMesh) {
      this.scene.remove(this.instancedMesh);
      this.instancedMesh.geometry.dispose();
      this.instancedMesh.material.dispose();
      this.instancedMesh = null;
    }

    const count = this.nodes.length;
    if (count === 0) return;

    // Alacsony poligonú gömb geometria (12x12 szegmens: ultragyors és sima)
    const geometry = new THREE.SphereGeometry(1, 12, 12);
    const material = new THREE.MeshStandardMaterial({
      roughness: 0.35,
      metalness: 0.25,
      emissiveIntensity: 0.35
    });

    this.instancedMesh = new THREE.InstancedMesh(geometry, material, count);
    this.instancedMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.instancedMesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3);

    this.baseColors = new Array(count);

    for (let i = 0; i < count; i++) {
      const n = this.nodes[i];
      const x = n.x || (Math.random() - 0.5) * 600;
      const y = n.y || (Math.random() - 0.5) * 600;
      const z = n.z || (Math.random() - 0.5) * 600;

      // Méretezés (val és csomópont típus alapján)
      let scale = n.val || 5.0;
      if (n.type === 'discipline') scale = Math.max(scale, 14.0);
      else if (n.type === 'strategy') scale = Math.max(scale, 9.0);
      else if (n.type === 'author') scale = Math.max(scale, 6.0);
      else scale = Math.max(scale, 3.5);

      this.dummyMatrix.makeScale(scale, scale, scale);
      this.dummyMatrix.setPosition(x, y, z);
      this.instancedMesh.setMatrixAt(i, this.dummyMatrix);

      // Alapszín hozzárendelés
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
        validLinks.push({ srcIdx: this.nodeIndexMap.get(srcId), tgtIdx: this.nodeIndexMap.get(tgtId), type: link.type });
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

      // Élszínek gradientje a két csomópont színe alapján
      const c1 = this.baseColors[l.srcIdx] || new THREE.Color(0x38bdf8);
      const c2 = this.baseColors[l.tgtIdx] || new THREE.Color(0xa855f7);

      colors[i * 6] = c1.r * 0.7;
      colors[i * 6 + 1] = c1.g * 0.7;
      colors[i * 6 + 2] = c1.b * 0.7;

      colors[i * 6 + 3] = c2.r * 0.7;
      colors[i * 6 + 4] = c2.g * 0.7;
      colors[i * 6 + 5] = c2.b * 0.7;
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

  getNodeColor(node) {
    if (this.options.colorMode === 'type') {
      const typeColors = {
        paper: '#00f3ff',
        author: '#fbbf24',
        strategy: '#f43f5e',
        discipline: '#10b981',
        asset: '#8b5cf6',
        topic: '#64748b'
      };
      return typeColors[node.type] || '#94a3b8';
    }

    if (this.options.colorMode === 'strategy') {
      if (node.has_strategy) return '#f43f5e';
      if (!node.is_direct_finance) return '#10b981';
      return '#38bdf8';
    }

    // Alapértelmezett: Diszciplína szerinti színezés
    return node.color || '#00f3ff';
  }

  // ─── Szomszédság Kiemelés & Halványítás (Dimming) ─────────────

  highlightNeighborhood(centerNodeId) {
    if (!this.instancedMesh) return;

    if (!centerNodeId) {
      // Visszaállítás minden alapszínre
      for (let i = 0; i < this.nodes.length; i++) {
        this.instancedMesh.setColorAt(i, this.baseColors[i]);
      }
      if (this.instancedMesh.instanceColor) {
        this.instancedMesh.instanceColor.needsUpdate = true;
      }
      if (this.linkSegments) {
        this.linkSegments.material.opacity = this.options.linkOpacity;
      }
      return;
    }

    const neighbors = this.adjacency.get(centerNodeId) || new Set();
    const centerIdx = this.nodeIndexMap.get(centerNodeId);

    const dimColor = new THREE.Color(0x111827); // Halvány sötétszürke

    for (let i = 0; i < this.nodes.length; i++) {
      const n = this.nodes[i];
      if (n.id === centerNodeId) {
        // Központi csomópont szuper fényes fehér/neon
        this.instancedMesh.setColorAt(i, new THREE.Color(0xffffff));
      } else if (neighbors.has(n.id)) {
        // Közvetlen szomszédok élénk alapszínben
        this.instancedMesh.setColorAt(i, this.baseColors[i]);
      } else {
        // Független csomópontok elhalványítva
        this.instancedMesh.setColorAt(i, dimColor);
      }
    }

    if (this.instancedMesh.instanceColor) {
      this.instancedMesh.instanceColor.needsUpdate = true;
    }

    // Élek halványítása
    if (this.linkSegments) {
      this.linkSegments.material.opacity = Math.max(0.15, this.options.linkOpacity * 0.5);
    }
  }

  // ─── Kamera Animáció (Cinematic Fly-To) ────────────────────────

  flyTo(targetX, targetY, targetZ, duration = 1200, offsetDist = 180) {
    const startPos = this.camera.position.clone();
    const startTarget = this.controls.target.clone();

    // Számítsuk ki a cél pozíciót úgy, hogy a kamera a célpont elé nézzen
    const endTarget = new THREE.Vector3(targetX, targetY, targetZ);
    const dir = new THREE.Vector3().subVectors(startPos, endTarget).normalize();
    if (dir.length() < 0.1) dir.set(0, 0.5, 1).normalize();

    const endPos = new THREE.Vector3().copy(endTarget).addScaledVector(dir, offsetDist);

    this.cameraAnimation = {
      startTime: performance.now(),
      duration: duration,
      startPos: startPos,
      endPos: endPos,
      startTarget: startTarget,
      endTarget: endTarget
    };
  }

  flyToNode(nodeId) {
    const idx = this.nodeIndexMap.get(nodeId);
    if (idx === undefined) return;
    const n = this.nodes[idx];
    this.flyTo(n.x, n.y, n.z, 1100, 160);
    this.selectedNodeId = nodeId;
    this.highlightNeighborhood(nodeId);
  }

  resetCamera() {
    this.flyTo(0, 0, 0, 1000, 1100);
    this.selectedNodeId = null;
    this.highlightNeighborhood(null);
  }

  // ─── Interakciók & Eseménykezelők ─────────────────────────────

  initEvents() {
    window.addEventListener('resize', this.onWindowResize.bind(this));
    
    // Egérmozgás hover detektáláshoz
    this.container.addEventListener('mousemove', (e) => {
      const rect = this.container.getBoundingClientRect();
      this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    });

    // Kattintás csomópont kiválasztáshoz
    this.container.addEventListener('click', (e) => {
      if (this.hoveredNodeId) {
        this.selectedNodeId = this.hoveredNodeId;
        this.highlightNeighborhood(this.selectedNodeId);
        if (typeof this.onNodeClick === 'function') {
          const idx = this.nodeIndexMap.get(this.selectedNodeId);
          this.onNodeClick(this.nodes[idx], e);
        }
      }
    });

    // Billentyűzet kezelés (WASD repülés)
    window.addEventListener('keydown', (e) => {
      this.keysDown[e.code] = true;
      if (e.code === 'KeyR') {
        this.resetCamera();
      }
      if (e.code === 'KeyF' && this.selectedNodeId) {
        this.flyToNode(this.selectedNodeId);
      }
    });

    window.addEventListener('keyup', (e) => {
      this.keysDown[e.code] = false;
    });
  }

  onWindowResize() {
    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;

    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();

    this.renderer.setSize(width, height);
    if (this.composer) {
      this.composer.setSize(width, height);
    }
  }

  handleKeyboardFlight(delta) {
    const speed = 400.0 * delta;
    const forward = new THREE.Vector3();
    this.camera.getWorldDirection(forward);
    forward.normalize();

    const right = new THREE.Vector3().crossVectors(forward, this.camera.up).normalize();

    if (this.keysDown['KeyW']) {
      this.camera.position.addScaledVector(forward, speed);
      this.controls.target.addScaledVector(forward, speed);
    }
    if (this.keysDown['KeyS']) {
      this.camera.position.addScaledVector(forward, -speed);
      this.controls.target.addScaledVector(forward, -speed);
    }
    if (this.keysDown['KeyD']) {
      this.camera.position.addScaledVector(right, speed);
      this.controls.target.addScaledVector(right, speed);
    }
    if (this.keysDown['KeyA']) {
      this.camera.position.addScaledVector(right, -speed);
      this.controls.target.addScaledVector(right, -speed);
    }
    if (this.keysDown['Space']) {
      this.camera.position.y += speed;
      this.controls.target.y += speed;
    }
    if (this.keysDown['ShiftLeft'] || this.keysDown['ShiftRight']) {
      this.camera.position.y -= speed;
      this.controls.target.y -= speed;
    }
  }

  // ─── Fő Renderelési Ciklus (60 FPS Render Loop) ───────────────

  animate(time) {
    requestAnimationFrame(this.animate);

    const delta = (time - this.lastTime) / 1000.0;
    this.lastTime = time;

    // FPS mérés
    this.frameCount++;
    if (this.frameCount % 20 === 0) {
      this.currentFps = Math.round(1.0 / Math.max(delta, 0.001));
      if (typeof this.onFpsUpdate === 'function') {
        this.onFpsUpdate(this.currentFps);
      }
    }

    // Billentyűzetes repülés
    this.handleKeyboardFlight(delta);

    // Kamera interpoláció (FlyTo animáció)
    if (this.cameraAnimation) {
      const elapsed = performance.now() - this.cameraAnimation.startTime;
      const t = Math.min(elapsed / this.cameraAnimation.duration, 1.0);
      // Smooth cubic ease-out
      const ease = 1 - Math.pow(1 - t, 3);

      this.camera.position.lerpVectors(this.cameraAnimation.startPos, this.cameraAnimation.endPos, ease);
      this.controls.target.lerpVectors(this.cameraAnimation.startTarget, this.cameraAnimation.endTarget, ease);

      if (t >= 1.0) {
        this.cameraAnimation = null;
      }
    }

    this.controls.update();

    // Csillagmező lassan forog
    if (this.starfield) {
      this.starfield.rotation.y += 0.00015;
    }

    // Raycasting hover detektálás (csak minden 2. képkockán a maximális GPU sebességért)
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

    // Kirajzolás Post-processing Bloom-mal vagy natív WebGL-lel
    if (this.composer && this.options.bloomEnabled) {
      this.composer.render();
    } else {
      this.renderer.render(this.scene, this.camera);
    }
  }
}

window.GraphEngine3D = GraphEngine3D;
