// ============================================================
// Three.js animated background — particle network
// Floating nodes connected by lines, reacts subtly to mouse.
// Lightweight, pauses when tab is hidden to save battery.
// ============================================================

(function initBackground() {
  const canvas = document.getElementById('bg-canvas');
  if (!canvas || typeof THREE === 'undefined') return;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.z = 50;

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  const baseColor = new THREE.Color(isLight ? 0x4263eb : 0x6c8cff);
  const accentColor = new THREE.Color(isLight ? 0x6741d9 : 0x8d6cff);

  // Build particle field
  const PARTICLE_COUNT = 90;
  const positions = new Float32Array(PARTICLE_COUNT * 3);
  const velocities = [];
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    positions[i * 3] = (Math.random() - 0.5) * 120;
    positions[i * 3 + 1] = (Math.random() - 0.5) * 80;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 60;
    velocities.push({
      x: (Math.random() - 0.5) * 0.04,
      y: (Math.random() - 0.5) * 0.04,
      z: (Math.random() - 0.5) * 0.02,
    });
  }

  const particleGeo = new THREE.BufferGeometry();
  particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const particleMat = new THREE.PointsMaterial({
    color: baseColor,
    size: 0.6,
    transparent: true,
    opacity: 0.85,
    sizeAttenuation: true,
  });
  const points = new THREE.Points(particleGeo, particleMat);
  scene.add(points);

  // Lines between nearby particles
  const MAX_LINES = PARTICLE_COUNT * 4;
  const linePositions = new Float32Array(MAX_LINES * 6);
  const lineColors = new Float32Array(MAX_LINES * 6);
  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));
  lineGeo.setAttribute('color', new THREE.BufferAttribute(lineColors, 3));
  const lineMat = new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.35,
  });
  const lines = new THREE.LineSegments(lineGeo, lineMat);
  scene.add(lines);

  // Mouse parallax
  const mouse = { x: 0, y: 0, targetX: 0, targetY: 0 };
  window.addEventListener('mousemove', (e) => {
    mouse.targetX = (e.clientX / window.innerWidth - 0.5) * 8;
    mouse.targetY = (e.clientY / window.innerHeight - 0.5) * 8;
  });

  // Resize
  function onResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  }
  window.addEventListener('resize', onResize);

  // Theme change observer
  const themeObserver = new MutationObserver(() => {
    const light = document.documentElement.getAttribute('data-theme') === 'light';
    particleMat.color = new THREE.Color(light ? 0x4263eb : 0x6c8cff);
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  let paused = false;
  document.addEventListener('visibilitychange', () => { paused = document.hidden; });

  const LINK_DIST = 14;

  function animate() {
    if (!paused) {
      const pos = particleGeo.attributes.position.array;
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        pos[i * 3] += velocities[i].x;
        pos[i * 3 + 1] += velocities[i].y;
        pos[i * 3 + 2] += velocities[i].z;

        // Wrap edges
        if (pos[i * 3] > 60) pos[i * 3] = -60;
        if (pos[i * 3] < -60) pos[i * 3] = 60;
        if (pos[i * 3 + 1] > 40) pos[i * 3 + 1] = -40;
        if (pos[i * 3 + 1] < -40) pos[i * 3 + 1] = 40;
      }
      particleGeo.attributes.position.needsUpdate = true;

      // Rebuild line geometry for nearby pairs
      let lineIdx = 0;
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        for (let j = i + 1; j < PARTICLE_COUNT; j++) {
          const dx = pos[i * 3] - pos[j * 3];
          const dy = pos[i * 3 + 1] - pos[j * 3 + 1];
          const dz = pos[i * 3 + 2] - pos[j * 3 + 2];
          const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
          if (dist < LINK_DIST && lineIdx < MAX_LINES) {
            linePositions[lineIdx * 6] = pos[i * 3];
            linePositions[lineIdx * 6 + 1] = pos[i * 3 + 1];
            linePositions[lineIdx * 6 + 2] = pos[i * 3 + 2];
            linePositions[lineIdx * 6 + 3] = pos[j * 3];
            linePositions[lineIdx * 6 + 4] = pos[j * 3 + 1];
            linePositions[lineIdx * 6 + 5] = pos[j * 3 + 2];

            const alpha = 1 - dist / LINK_DIST;
            lineColors[lineIdx * 6] = baseColor.r * alpha;
            lineColors[lineIdx * 6 + 1] = baseColor.g * alpha;
            lineColors[lineIdx * 6 + 2] = baseColor.b * alpha;
            lineColors[lineIdx * 6 + 3] = accentColor.r * alpha;
            lineColors[lineIdx * 6 + 4] = accentColor.g * alpha;
            lineColors[lineIdx * 6 + 5] = accentColor.b * alpha;
            lineIdx++;
          }
        }
      }
      // Clear unused
      for (let k = lineIdx; k < MAX_LINES; k++) {
        for (let n = 0; n < 6; n++) linePositions[k * 6 + n] = 0;
      }
      lineGeo.attributes.position.needsUpdate = true;
      lineGeo.attributes.color.needsUpdate = true;
      lineGeo.setDrawRange(0, lineIdx * 2);

      // Mouse parallax
      mouse.x += (mouse.targetX - mouse.x) * 0.04;
      mouse.y += (mouse.targetY - mouse.y) * 0.04;
      camera.position.x = mouse.x;
      camera.position.y = -mouse.y;
      camera.lookAt(scene.position);

      // Gentle rotation
      points.rotation.y += 0.0008;
      lines.rotation.y = points.rotation.y;

      renderer.render(scene, camera);
    }
    requestAnimationFrame(animate);
  }
  animate();
})();
