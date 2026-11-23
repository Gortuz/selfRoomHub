// Panel de selfRoomHub. ES2015 sin dependencias para que funcione también en navegadores viejos (iPod).
(function () {
  "use strict";

  var DEVICE = "parlantes";   // id del enchufe en devices.yaml
  var BT = "parlantes";       // id en la sección bluetooth de devices.yaml
  var NIGHT_FROM = 23, NIGHT_TO = 6;

  var $ = function (id) { return document.getElementById(id); };
  var body = document.body;

  // --- Token: llega en #token=..., se guarda y se quita de la URL ---
  var token = null;
  var m = location.hash.match(/token=([^&]+)/);
  try {
    if (m) {
      token = decodeURIComponent(m[1]);
      localStorage.setItem("srh-token", token);
    } else {
      token = localStorage.getItem("srh-token");
    }
  } catch (e) { token = m ? decodeURIComponent(m[1]) : null; }
  if (m && history.replaceState) history.replaceState(null, "", location.pathname);
  if (!token) { $("setup").hidden = false; }

  // Sin token (p. ej. la app de pantalla de inicio de iOS tiene su propio almacenamiento): se pega aquí
  $("setup-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var candidate = $("setup-token").value.trim();
    fetch("/devices", { headers: { Authorization: "Bearer " + candidate } })
      .then(function (r) {
        if (r.status === 401) throw new Error("Ese token no es válido. Cópialo de nuevo.");
        if (!r.ok) throw new Error("El servidor respondió " + r.status + ".");
        try { localStorage.setItem("srh-token", candidate); } catch (err) { /* sin almacenamiento: dura esta sesión */ }
        token = candidate;
        location.reload();
      })
      .catch(function (err) {
        $("setup-error").textContent = err.message || "No hay conexión con el servidor.";
        $("setup-error").hidden = false;
      });
  });

  function api(method, path, data) {
    var opts = { method: method, headers: { Authorization: "Bearer " + token } };
    if (data !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(data);
    }
    return fetch(path, opts).then(function (r) {
      if (r.status === 401) {
        try { localStorage.removeItem("srh-token"); } catch (e) { /* nada */ }
        $("setup").hidden = false;
      }
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          var err = new Error(typeof b.detail === "string" ? b.detail : "Error " + r.status);
          err.status = r.status;
          throw err;
        });
      }
      return r.json();
    });
  }

  // --- Reloj y fecha ---
  var dateFmt;
  try { dateFmt = new Intl.DateTimeFormat("es-EC", { weekday: "short", day: "numeric", month: "short" }); }
  catch (e) { dateFmt = null; }

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function tick() {
    var now = new Date();
    var hhmm = pad(now.getHours()) + ":" + pad(now.getMinutes());
    $("clock").textContent = hhmm;
    if (body.classList.contains("idle") && $("title").textContent !== hhmm) {
      $("title").textContent = hhmm;
      fitTitle();
    }
    $("clock").setAttribute("datetime", now.toISOString());
    $("date").textContent = dateFmt ? dateFmt.format(now) : now.toDateString();
    var h = now.getHours();
    // El modo lo decide el backend (escenas y horario); si no responde, se usa la hora local
    var night = state.mode ? state.mode === "night" : (h >= NIGHT_FROM || h < NIGHT_TO);
    body.classList.toggle("night", night);
    $("sky-clock").textContent = hhmm;
    $("sky-date").textContent = $("date").textContent;
    if (typeof drawSky === "function") drawSky(now);
  }

  // --- Estado ---
  var state = {
    power: null,        // true / false / null (sin respuesta)
    audioHere: null,    // el servidor tiene el parlante Bluetooth
    btAvailable: true,  // Shizuku activo
    battery: null,      // última lectura de /battery (con "advice")
    mode: null,         // "day" | "night" según /mode
    timerEnd: null,     // instante local (ms) en que se apagan los parlantes
    offline: false,
    playing: false,
    volume: null
  };

  // --- Lo que suena ---
  var lastArt = null;

  var DEFAULT_INKS = ["#ffe600", "#ff3ea5", "#39ff7a"];

  // Tres tintas de afiche desde la portada: los tonos más presentes, llevados a fluorescente
  function inksFrom(img) {
    try {
      var size = 24, c = document.createElement("canvas");
      c.width = c.height = size;
      var ctx = c.getContext("2d");
      ctx.drawImage(img, 0, 0, size, size);
      var d = ctx.getImageData(0, 0, size, size).data, bins = [];
      for (var b = 0; b < 12; b++) bins.push({ hue: b * 30, weight: 0 });
      for (var i = 0; i < d.length; i += 4) {
        var r = d[i] / 255, g = d[i + 1] / 255, bl = d[i + 2] / 255;
        var max = Math.max(r, g, bl), min = Math.min(r, g, bl), delta = max - min;
        var light = (max + min) / 2;
        var sat = delta === 0 ? 0 : delta / (1 - Math.abs(2 * light - 1));
        if (sat < 0.25 || light < 0.12 || light > 0.92) continue;
        var h = max === r ? ((g - bl) / delta) % 6 : max === g ? (bl - r) / delta + 2 : (r - g) / delta + 4;
        h = (h * 60 + 360) % 360;
        bins[Math.floor(h / 30) % 12].weight += sat;
      }
      var picked = bins.filter(function (x) { return x.weight > 2; })
        .sort(function (a, b2) { return b2.weight - a.weight; }).slice(0, 3)
        .map(function (x) { return x.hue + 15; });
      if (!picked.length) return DEFAULT_INKS;
      var inks = picked.map(function (h) {
        // Los amarillos y verdes ya son claros; los azules necesitan más luz para leerse sobre negro
        var l = h > 200 && h < 290 ? 68 : 58;
        return "hsl(" + Math.round(h) + ", 100%, " + l + "%)";
      });
      while (inks.length < 3) inks.push(DEFAULT_INKS[inks.length]);
      return inks;
    } catch (e) { return DEFAULT_INKS; }
  }

  function setInks(inks) {
    var root = document.documentElement.style;
    root.setProperty("--ink-1", inks[0]);
    root.setProperty("--ink-2", inks[1]);
    root.setProperty("--ink-3", inks[2]);
  }

  function showArt(url) {
    if (url === lastArt) return;
    lastArt = url;
    var cover = $("cover");
    if (!url) {
      cover.innerHTML = "";
      setInks(DEFAULT_INKS);
      return;
    }
    var img = new Image();
    img.alt = "";
    img.onload = function () {
      cover.innerHTML = "";
      cover.appendChild(img);
      setInks(inksFrom(img));
    };
    img.src = url;
  }

  // "Octopus's Garden - Remastered 2009" → ["Octopus's Garden", "Remastered 2009"]
  function splitTitle(t) {
    var m = t.match(/^(.+?)\s+[-\u2013\u2014]\s+(.+)$/) || t.match(/^(.+?)\s*[(\[]([^)\]]+)[)\]]\s*$/);
    return m ? [m[1], m[2]] : [t, ""];
  }

  // El título ocupa todo el espacio libre del afiche: se busca el tamaño mayor que entra
  function fitTitle() {
    var title = $("title"), poster = $("track");
    var avail = poster.clientHeight - ($("artist").offsetHeight || 0) - ($("version").offsetHeight || 0) - 18;
    var width = poster.clientWidth;
    if (avail <= 0 || width <= 0) return;
    // Tope: el título manda, pero deja aire a la hora y a los controles
    var size = Math.min(avail, body.classList.contains("idle") ? 220 : 84);
    title.style.fontSize = size + "px";
    while (size > 18 && (title.scrollHeight > avail || title.scrollWidth > width)) {
      size -= 3;
      title.style.fontSize = size + "px";
    }
  }
  window.addEventListener("resize", fitTitle);
  // La fuente del afiche llega después del primer dibujo: volver a medir cuando cargue
  if (document.fonts) {
    if (document.fonts.ready) document.fonts.ready.then(fitTitle);
    if (document.fonts.addEventListener) document.fonts.addEventListener("loadingdone", fitTitle);
  }
  setTimeout(fitTitle, 1500);

  function renderNowPlaying(np) {
    var hasTrack = !!(np && np.title);
    state.playing = !!(np && np.playing);
    body.classList.toggle("idle", !hasTrack);
    $("track").classList.toggle("paused", hasTrack && !np.playing);
    var parts = hasTrack ? splitTitle(np.title) : [$("clock").textContent, ""];
    var artist = hasTrack ? (np.artist || "") : "";
    if ($("title").textContent !== parts[0] || $("version").textContent !== parts[1] || $("artist").textContent !== artist) {
      $("title").textContent = parts[0];
      $("version").textContent = parts[1];
      $("version").hidden = !parts[1];
      $("artist").textContent = artist;
      fitTitle();
    }
    showArt(hasTrack ? np.art_url : null);

    if (np && typeof np.position_ms === "number") {
      playback = { pos: np.position_ms, at: Date.now(), playing: !!np.playing, duration: np.duration_ms };
    } else {
      playback = { pos: null, at: 0, playing: false, duration: null };
    }
    loadLyrics(hasTrack ? np : null);
    autoView(hasTrack && !!np.playing);

    var pp = $("playpause");
    pp.classList.toggle("playing", state.playing);
    pp.setAttribute("aria-label", state.playing ? "Pausar" : "Reproducir");

    if (np && typeof np.volume === "number") {
      if (Date.now() - lastVolumeSet > 3000) state.volume = np.volume;
      // Tras mover el fader, el servidor tarda un poco en confirmar: no volver atrás mientras tanto
      if (!dragging && Date.now() - lastVolumeSet > 3000) showVolume(np.volume);
    }
    // Los controles solo tienen sentido si la app del servidor está informando
    $("transport").hidden = state.volume === null;
    $("fader").hidden = state.volume === null;
  }

  // --- Reproducción y volumen ---
  function command(action, value) {
    return api("POST", "/media/command", value === undefined ? { action: action } : { action: action, value: value })
      .catch(function (e) { flash("No se pudo enviar la orden: " + e.message); });
  }

  $("prev").addEventListener("click", function () { command("previous"); });
  $("next").addEventListener("click", function () { command("next"); });
  $("playpause").addEventListener("click", function () {
    // Respuesta inmediata en pantalla; el estado real llega en el siguiente sondeo
    state.playing = !state.playing;
    $("playpause").classList.toggle("playing", state.playing);
    command("toggle");
  });

  // Canal vertical: se arrastra con el pulgar o se usa + / −. Android tiene 16 pasos (0–15).
  var dragging = false;
  var rail = $("volume");
  var STEPS = 15;

  function showVolume(v) {
    $("volume-value").textContent = v + " %";
    $("rail-fill").style.height = v + "%";
    $("rail-cap").style.bottom = v + "%";
    rail.setAttribute("aria-valuenow", v);
    rail.setAttribute("aria-valuetext", v + " %");
  }

  function snap(v) { return Math.round(Math.round(v / 100 * STEPS) / STEPS * 100); }

  var lastVolumeSet = 0;
  function sendVolume(v) {
    v = Math.max(0, Math.min(100, v));
    lastVolumeSet = Date.now();
    state.volume = v;
    showVolume(v);
    command("volume", v);
  }

  function valueAt(clientY) {
    var r = rail.getBoundingClientRect();
    var v = (1 - (clientY - r.top) / r.height) * 100;
    return snap(Math.max(0, Math.min(100, v)));
  }

  function railDown(e) {
    dragging = true;
    rail.classList.add("dragging");
    if (rail.setPointerCapture && e.pointerId !== undefined) rail.setPointerCapture(e.pointerId);
    showVolume(valueAt(e.clientY));
    e.preventDefault();
  }
  function railMove(e) { if (dragging) showVolume(valueAt(e.clientY)); }
  function railUp(e) {
    if (!dragging) return;
    dragging = false;
    rail.classList.remove("dragging");
    sendVolume(valueAt(e.clientY));
  }
  rail.addEventListener("pointerdown", railDown);
  rail.addEventListener("pointermove", railMove);
  rail.addEventListener("pointerup", railUp);
  rail.addEventListener("pointercancel", function () { dragging = false; rail.classList.remove("dragging"); });

  function stepBy(n) {
    var current = state.volume === null ? 0 : state.volume;
    var step = Math.round(current / 100 * STEPS) + n;
    sendVolume(Math.round(Math.max(0, Math.min(STEPS, step)) / STEPS * 100));
  }
  $("vol-up").addEventListener("click", function () { stepBy(1); });
  $("vol-down").addEventListener("click", function () { stepBy(-1); });
  rail.addEventListener("keydown", function (e) {
    if (e.key === "ArrowUp" || e.key === "ArrowRight") { stepBy(1); e.preventDefault(); }
    if (e.key === "ArrowDown" || e.key === "ArrowLeft") { stepBy(-1); e.preventDefault(); }
  });

  // --- Menú de parlantes ---
  function led(on) { return '<span class="led' + (on ? " on" : "") + '" aria-hidden="true"></span>'; }

  function renderSheet() {
    var powerText = state.power === null ? "Sin respuesta" : state.power ? "Encendidos" : "Apagados";
    $("fact-power").innerHTML = led(state.power === true) + powerText;

    var audioText;
    if (state.power === false) audioText = "—";
    else if (state.audioHere === null) audioText = state.btAvailable ? "Desconocido" : "Sin control (Shizuku inactivo)";
    else audioText = state.audioHere ? "Sonando en este equipo" : "En otro equipo";
    $("fact-audio").innerHTML = led(state.audioHere === true && state.power === true) + audioText;

    var actPower = $("act-power");
    actPower.disabled = state.power === null;
    actPower.textContent = state.power ? "Apagar parlantes" : "Encender parlantes";

    $("act-audio").hidden = !(state.power && state.audioHere === false && state.btAvailable);
  }

  function sheetMessage(text) {
    $("sheet-message").textContent = text || "";
    $("sheet-message").hidden = !text;
  }

  function openSheet() {
    sheetMessage("");
    renderSheet();
    $("sheet").hidden = false;
    $("act-close").focus();
    refreshDevices();
    refreshAudio();
  }
  function closeSheet() { $("sheet").hidden = true; $("speakers").focus(); }

  $("speakers").addEventListener("click", openSheet);
  $("act-close").addEventListener("click", closeSheet);
  $("sheet").addEventListener("click", function (e) { if (e.target === $("sheet")) closeSheet(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !$("sheet").hidden) closeSheet(); });

  function busy(el, on) { el.classList.toggle("busy", on); el.disabled = on; }

  $("act-power").addEventListener("click", function () {
    var btn = $("act-power"), turnOn = !state.power;
    busy(btn, true);
    sheetMessage("");
    api("POST", "/devices/" + DEVICE + "/power", { on: turnOn })
      .then(function (d) {
        state.power = d.online ? d.on : null;
        render();
        // Al encender, los parlantes tardan unos segundos en reconectarse por Bluetooth
        if (turnOn) setTimeout(refreshAudio, 6000);
      })
      .catch(function (e) { sheetMessage("No se pudo " + (turnOn ? "encender" : "apagar") + ": " + e.message); })
      .then(function () { busy(btn, false); renderSheet(); });
  });

  $("act-audio").addEventListener("click", function () {
    var btn = $("act-audio");
    busy(btn, true);
    sheetMessage("");
    api("POST", "/bluetooth/" + BT + "/connect")
      .then(function (d) { state.audioHere = d.connected; render(); })
      .catch(function () { sheetMessage("No se pudo traer el audio. Si la Mac tiene los parlantes, usa Music mode desde la Mac."); })
      .then(function () { busy(btn, false); renderSheet(); });
  });

  // --- Render general ---
  function render() {
    $("speakers").setAttribute("aria-pressed", state.power ? "true" : "false");

    var notice = "", calm = false, b = state.battery;
    var advice = b && b.advice;
    if (state.offline) notice = "No hay conexión con el servidor. Reintentando…";
    else if (advice === "critical") notice = "Batería crítica (" + b.percentage + " %): conecta el cargador ya.";
    else if (state.power === null) notice = "Los parlantes no responden: revisa el enchufe y el Wi-Fi.";
    else if (advice === "connect") notice = "Batería al " + b.percentage + " %: conecta el cargador.";
    else if (advice === "disconnect") { notice = "Batería al " + b.percentage + " %: ya puedes desconectar el cargador."; calm = true; }
    else if (!state.btAvailable) notice = "Cambio de audio desactivado: abre Shizuku y toca Start.";
    $("notice").textContent = notice;
    $("notice").hidden = !notice;
    $("notice").classList.toggle("calm", calm);

    if (!$("sheet").hidden) renderSheet();
  }

  function flash(message) {
    $("notice").textContent = message;
    $("notice").hidden = false;
    setTimeout(render, 6000);
  }

  // Mantener presionado el reloj abre Ajustes de Android (salida del modo kiosco)
  var holdTimer = null;
  function holdStart() {
    holdTimer = setTimeout(function () {
      if (window.Android && window.Android.openSettings) window.Android.openSettings();
    }, 2000);
  }
  function holdEnd() { clearTimeout(holdTimer); }
  ["touchstart", "mousedown"].forEach(function (ev) { $("clock").addEventListener(ev, holdStart); });
  ["touchend", "touchcancel", "mouseup", "mouseleave"].forEach(function (ev) { $("clock").addEventListener(ev, holdEnd); });

  // --- Sondeo ---
  function refreshNowPlaying() {
    if (!token) return;
    api("GET", "/now-playing").then(renderNowPlaying).catch(function () {});
  }

  function refreshDevices() {
    if (!token) return;
    api("GET", "/devices/" + DEVICE)
      .then(function (d) {
        var wasOn = state.power;
        state.power = d.online ? d.on : null;
        state.offline = false;
        state.timerEnd = d.on && typeof d.timer === "number" ? Date.now() + d.timer * 1000 : null;
        // Parlantes recién apagados (p. ej. por el temporizador): soltar la pantalla ya,
        // salvo que alguien la haya tocado hace un momento
        if (wasOn === true && state.power === false && Date.now() - lastTouch > 10000) {
          lastTouch = 0;
          updateAwake();
        }
        renderTimer();
      })
      .catch(function (e) { if (!e.status) state.offline = true; else state.power = null; })
      .then(render);
  }

  function refreshAudio() {
    if (!token) return;
    api("GET", "/bluetooth")
      .then(function (list) {
        var t = list.filter(function (x) { return x.id === BT; })[0];
        state.audioHere = t ? t.connected : null;
      })
      .catch(function () { state.audioHere = null; })
      .then(render);
  }

  // --- Apagado programado ---
  var MOON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 2.5a9.5 9.5 0 1 0 7 15.9A8 8 0 0 1 14.5 2.5z"/></svg>';
  function timerMinutes() {
    if (!state.timerEnd) return null;
    return Math.max(0, Math.ceil((state.timerEnd - Date.now()) / 60000));
  }
  function renderTimer() {
    var m = timerMinutes(), text = m === null ? "" : m + " min";
    $("sleep-timer").innerHTML = m === null ? "" : MOON + text;
    $("sleep-timer").setAttribute("aria-label", m === null ? "" : "Los parlantes se apagan en " + text);
    $("sleep-timer").hidden = m === null;
    body.classList.toggle("timer-on", m !== null);
    $("sky-timer").textContent = m === null ? "" : "Los parlantes se apagan en " + text;
    $("sky-timer").hidden = m === null;
    $("fact-timer-row").hidden = m === null;
    $("fact-timer").textContent = text;
    $("act-timer").hidden = m === null;
  }
  setInterval(renderTimer, 15000);

  $("act-timer").addEventListener("click", function () {
    var btn = $("act-timer");
    busy(btn, true);
    api("POST", "/devices/" + DEVICE + "/timer", { minutes: 0 })
      .then(function () { state.timerEnd = null; renderTimer(); })
      .catch(function (e) { sheetMessage("No se pudo cancelar el temporizador: " + e.message); })
      .then(function () { busy(btn, false); renderSheet(); });
  });

  // --- Batería del servidor ---
  function renderBattery(el, b) {
    if (!b) { el.hidden = true; return; }
    var p = Math.max(0, Math.min(100, b.percentage));
    var w = Math.max(1.5, 19 * p / 100);
    el.innerHTML =
      '<svg viewBox="0 0 30 15" aria-hidden="true">' +
      '<rect class="shell" x="1" y="1.5" width="24" height="12" rx="1"/>' +
      '<rect class="cap" x="26" y="5" width="2.5" height="5"/>' +
      '<rect class="level" x="3.5" y="4" width="' + w.toFixed(1) + '" height="7"/>' +
      (b.charging ? '<path class="bolt" d="M14.5 2.5 9.5 8.5h4l-1.5 4.5 5.5-6.5h-4z"/>' : "") +
      "</svg>" + p + " %";
    el.setAttribute("aria-label", "Batería " + p + " %" + (b.charging ? ", cargando" : ""));
    el.classList.toggle("low", p < 20 && !b.charging);
    el.hidden = false;
  }

  function refreshBattery() {
    if (!token) return;
    api("GET", "/battery")
      .then(function (b) { state.battery = b; renderBattery($("battery"), b); renderBattery($("sky-battery"), b); render(); })
      .catch(function () { state.battery = null; renderBattery($("battery"), null); renderBattery($("sky-battery"), null); render(); });
  }

  // --- Modo día/noche (lo cambian las escenas; el horario es el respaldo) ---
  function refreshMode() {
    if (!token) return;
    api("GET", "/mode")
      .then(function (m) {
        var was = state.mode;
        state.mode = m.mode;
        // Al entrar en modo noche el panel pasa al reloj
        if (was && was !== "night" && m.mode === "night") setView(2);
        tick();
        updateAwake();
      })
      .catch(function () { state.mode = null; });
  }

  function refreshHealth() {
    fetch("/health").then(function (r) { return r.json(); })
      .then(function (h) { state.btAvailable = h.bluetooth !== "unavailable"; state.offline = false; })
      .catch(function () { state.offline = true; })
      .then(render);
  }


  // --- Vistas: Letra (0) ← Música (1) → Reloj (2) ---
  var views = $("views");
  var view = 1;
  function setView(i) {
    view = Math.max(0, Math.min(2, i));
    views.setAttribute("data-view", view);
    views.style.transform = "";
    if (view === 0) syncLyrics(true);
  }
  // ¿Hay notch? Se mide el margen seguro de cada lado para poner el indicador en esa franja libre
  function placeDots() {
    var probe = document.createElement("div");
    probe.style.cssText = "position:fixed;visibility:hidden;padding-left:env(safe-area-inset-left);padding-right:env(safe-area-inset-right)";
    document.body.appendChild(probe);
    var cs = getComputedStyle(probe), left = parseFloat(cs.paddingLeft) || 0, right = parseFloat(cs.paddingRight) || 0;
    document.body.removeChild(probe);
    body.classList.toggle("notch-left", left >= 16 && left >= right);
    body.classList.toggle("notch-right", right >= 16 && right > left);
  }
  placeDots();
  window.addEventListener("resize", placeDots);
  document.addEventListener("keydown", function (e) {
    if (!$("sheet").hidden) return;
    if (e.key === "ArrowLeft") setView(view - 1);
    if (e.key === "ArrowRight") setView(view + 1);
  });

  // Deslizar con el dedo: solo si el gesto es horizontal y no empieza en el fader
  var swipe = null;
  views.addEventListener("pointerdown", function (e) {
    if (e.target.closest && e.target.closest(".rail")) return;
    swipe = { x: e.clientX, y: e.clientY, dx: 0, active: false };
  });
  views.addEventListener("pointermove", function (e) {
    if (!swipe) return;
    var dx = e.clientX - swipe.x, dy = e.clientY - swipe.y;
    if (!swipe.active) {
      if (Math.abs(dx) < 12 || Math.abs(dx) < Math.abs(dy)) return;
      swipe.active = true;
      views.classList.add("dragging");
    }
    swipe.dx = dx;
    views.style.transform = "translateX(calc(" + (-100 * view) + "vw + " + dx + "px))";
  });
  function endSwipe() {
    if (!swipe) return;
    var s2 = swipe;
    swipe = null;
    views.classList.remove("dragging");
    if (!s2.active) return;
    if (s2.dx < -60) setView(view + 1);
    else if (s2.dx > 60) setView(view - 1);
    else setView(view);
  }
  views.addEventListener("pointerup", endSwipe);
  views.addEventListener("pointercancel", endSwipe);
  // Un toque que terminó en deslizamiento no debe accionar el botón bajo el dedo
  views.addEventListener("click", function (e) {
    if (views.getAttribute("data-swiped") === "1") { e.stopPropagation(); e.preventDefault(); views.removeAttribute("data-swiped"); }
  }, true);
  views.addEventListener("pointerup", function () { if (views.classList.contains("dragging")) views.setAttribute("data-swiped", "1"); }, true);

  // Con música suena la vista de música; en silencio, el reloj. Elegir a mano vale hasta el próximo cambio.
  var lastWantsMusic = null;
  function autoView(wantsMusic) {
    if (wantsMusic === lastWantsMusic) return;
    lastWantsMusic = wantsMusic;
    setView(wantsMusic ? 1 : 2);
  }

  // --- Letra sincronizada (LRCLIB vía backend) ---
  var lyrics = { key: null, synced: null, plain: null };
  var playback = { pos: null, at: 0, playing: false, duration: null };

  function currentPos() {
    if (playback.pos === null) return null;
    return playback.pos + (playback.playing ? Date.now() - playback.at : 0);
  }

  function lyricsState(text) {
    $("lyrics-state").textContent = text || "";
    $("lyrics-state").hidden = !text;
  }

  // Texto de una línea que no cabe: se recorre de ida y vuelta, a velocidad de lectura
  function marquee(span) {
    var box = span.parentNode;
    box.classList.remove("moving");
    var overflow = span.offsetWidth - box.clientWidth;
    if (overflow > 2) {
      box.style.setProperty("--marquee-shift", -overflow + "px");
      box.style.setProperty("--marquee-time", Math.max(5, overflow / 30 + 3) + "s");
      box.classList.add("moving");
    }
  }
  function refreshMarquees() { marquee($("lyrics-title")); marquee($("lyrics-artist")); }
  window.addEventListener("resize", refreshMarquees);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(refreshMarquees);

  function loadLyrics(np) {
    var key = np && np.title ? np.title + "|" + (np.artist || "") : null;
    if (key === lyrics.key) return;
    lyrics = { key: key, synced: null, plain: null };
    $("lyrics-lines").innerHTML = "";
    $("lyrics-scroll").classList.remove("plain");
    $("lyrics-title").textContent = np && np.title ? splitTitle(np.title)[0] : "";
    $("lyrics-artist").textContent = np && np.artist ? np.artist : "";
    refreshMarquees();
    $("lyrics-cover").innerHTML = "";
    if (np && np.art_url) {
      var img = new Image();
      img.alt = "";
      img.src = np.art_url;
      $("lyrics-cover").appendChild(img);
    }
    if (!key) { lyricsState("No suena nada."); return; }
    lyricsState("Buscando la letra…");
    api("GET", "/lyrics")
      .then(function (l) {
        if (lyrics.key !== key) return;
        if (l.instrumental) { lyricsState("Instrumental."); return; }
        lyrics.synced = l.synced && l.synced.length ? l.synced : null;
        lyrics.plain = l.plain || null;
        var lines = lyrics.synced ? lyrics.synced.map(function (x) { return x.line; }) : (lyrics.plain || "").split("\n");
        var ol = $("lyrics-lines");
        lines.forEach(function (line) {
          var li = document.createElement("li");
          li.textContent = line || "♪";
          ol.appendChild(li);
        });
        $("lyrics-scroll").classList.toggle("plain", !lyrics.synced);
        lyricsState("");
        syncLyrics(true);
      })
      .catch(function (e) {
        if (lyrics.key !== key) return;
        lyricsState(e.status === 404 ? "Esta canción no tiene letra en LRCLIB." : "No se pudo buscar la letra. Reintentando con la próxima canción.");
      });
  }

  var lastLine = -1;
  function syncLyrics(force) {
    if (view !== 0 || !lyrics.synced) return;
    var pos = currentPos();
    if (pos === null) return;
    var idx = -1;
    for (var i = 0; i < lyrics.synced.length; i++) { if (lyrics.synced[i].t <= pos + 250) idx = i; else break; }
    if (idx === lastLine && !force) return;
    lastLine = idx;
    var items = $("lyrics-lines").children;
    for (var j = 0; j < items.length; j++) {
      items[j].className = j === idx ? "now" : j < idx ? "past" : "";
    }
    // La línea actual queda a un tercio de la altura
    var target = items[Math.max(0, idx)];
    if (target) {
      var scroll = $("lyrics-scroll");
      var offset = target.offsetTop - scroll.clientHeight * 0.36;
      $("lyrics-lines").style.transform = "translateY(" + (-offset) + "px)";
    }
  }
  setInterval(function () { syncLyrics(false); }, 250);

  // --- Reloj ilustrado: afiche generativo de cerros y sol ---
  var SKIES = {
    alba:      { inks: ["#ff7a1a", "#ff3ea5", "#ffe600"], sun: "#ffe600", ring: "#ff3ea5", hills: [["#ff3ea5", "#7a2cff"], ["#ff7a1a", "#ff3ea5"], ["#ffe600", "#ff7a1a"]] },
    dia:       { inks: ["#ffe600", "#39ff7a", "#2ee6ff"], sun: "#ffe600", ring: "#ff7a1a", hills: [["#2ee6ff", "#1f8fff"], ["#39ff7a", "#2ee6ff"], ["#ffe600", "#39ff7a"]] },
    atardecer: { inks: ["#ffb000", "#ff3ea5", "#9b4dff"], sun: "#ff7a1a", ring: "#ffe600", hills: [["#9b4dff", "#5a1fa8"], ["#ff3ea5", "#9b4dff"], ["#ff7a1a", "#ff3ea5"]] },
    noche:     { inks: ["#8fa8ff", "#9b4dff", "#ff3ea5"], sun: "#f2ede3", ring: "#8fa8ff", hills: [["#2b2a6b", "#3b2f8f"], ["#3b2f8f", "#5a1fa8"], ["#5a1fa8", "#7a2cff"]] }
  };
  function period(h) { return h >= 5 && h < 8 ? "alba" : h >= 8 && h < 17 ? "dia" : h >= 17 && h < 19 ? "atardecer" : "noche"; }

  // Azar repetible: los cerros cambian cada día, no en cada dibujo
  function rng(seed) {
    return function () {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      var t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  var lastSky = null;
  function drawSky(now) {
    var h = now.getHours(), name = period(h);
    var stamp = now.toDateString() + name + Math.floor((h * 60 + now.getMinutes()) / 10);
    if (stamp === lastSky) return;
    lastSky = stamp;
    var sky = SKIES[name];
    var root = document.documentElement.style;
    root.setProperty("--sky-1", sky.inks[0]);
    root.setProperty("--sky-2", sky.inks[1]);
    root.setProperty("--sky-3", sky.inks[2]);

    var W = 1600, H = 740, svg = [];
    var day = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 86400000;
    var rand = rng(Math.floor(day));

    // Bandas de cada cerro (patrón de tinta plana, como las letras chicha)
    svg.push("<defs>");
    sky.hills.forEach(function (c, i) {
      var band = 10 + i * 6;
      svg.push('<pattern id="band' + i + '" patternUnits="userSpaceOnUse" width="' + W + '" height="' + band * 2 + '">' +
        '<rect width="' + W + '" height="' + band + '" fill="' + c[0] + '"/>' +
        '<rect y="' + band + '" width="' + W + '" height="' + band + '" fill="' + c[1] + '"/></pattern>');
    });
    svg.push("</defs>");

    if (name === "noche") {
      for (var k = 0; k < 46; k++) {
        var sx = rand() * W, sy = rand() * 460, sz = 3 + rand() * 5;
        svg.push('<rect x="' + sx.toFixed(0) + '" y="' + sy.toFixed(0) + '" width="' + sz.toFixed(1) + '" height="' + sz.toFixed(1) + '" fill="#f2ede3" opacity="' + (0.35 + rand() * 0.5).toFixed(2) + '"/>');
      }
    }

    // Sol (o luna): anillos concéntricos que recorren el cielo durante el periodo
    var spans = { alba: [5, 8], dia: [8, 17], atardecer: [17, 19], noche: [19, 29] };
    var sp = spans[name], hh = h < 5 ? h + 24 : h;
    var f = Math.max(0, Math.min(1, (hh + now.getMinutes() / 60 - sp[0]) / (sp[1] - sp[0])));
    var cx = 820 + f * 600, cy = 470 - Math.sin(Math.PI * f) * 250, r = 88;
    svg.push('<circle cx="' + cx.toFixed(0) + '" cy="' + cy.toFixed(0) + '" r="' + r + '" fill="' + sky.ring + '"/>');
    svg.push('<circle cx="' + cx.toFixed(0) + '" cy="' + cy.toFixed(0) + '" r="' + (r * 0.74).toFixed(0) + '" fill="' + sky.sun + '"/>');
    svg.push('<circle cx="' + cx.toFixed(0) + '" cy="' + cy.toFixed(0) + '" r="' + (r * 0.42).toFixed(0) + '" fill="' + sky.ring + '"/>');

    // Tres cordilleras, de la más lejana a la más cercana
    [560, 630, 700].forEach(function (base, i) {
      var pts = [], step = 200 - i * 30, x = -step;
      while (x <= W + step) {
        pts.push([x, base - (30 + rand() * (120 - i * 30))]);
        x += step * (0.7 + rand() * 0.6);
      }
      var d = "M0 " + H + " L" + pts[0][0] + " " + pts[0][1];
      for (var q = 1; q < pts.length; q++) {
        var mx = (pts[q - 1][0] + pts[q][0]) / 2, my = (pts[q - 1][1] + pts[q][1]) / 2;
        d += " Q" + pts[q - 1][0].toFixed(0) + " " + pts[q - 1][1].toFixed(0) + " " + mx.toFixed(0) + " " + my.toFixed(0);
      }
      d += " L" + W + " " + H + " Z";
      svg.push('<path d="' + d + '" fill="url(#band' + i + ')"/>');
    });
    $("sky-art").innerHTML = svg.join("");
  }

  // --- Brillo (solo dentro de la app kiosco) y apagado de pantalla por inactividad ---
  var android = window.Android || null;
  var hasScreenApi = !!(android && android.setKeepAwake && android.setBrightness);

  var lightRail = $("light-rail"), lightDragging = false;
  function showLight(v) {
    $("light-value").textContent = v + " %";
    $("light-fill").style.height = v + "%";
    $("light-cap").style.bottom = v + "%";
    lightRail.setAttribute("aria-valuenow", v);
  }
  function setLight(v) {
    v = Math.max(2, Math.min(100, Math.round(v)));
    showLight(v);
    if (hasScreenApi) android.setBrightness(v / 100);
  }
  function lightAt(clientY) {
    var r = lightRail.getBoundingClientRect();
    return (1 - (clientY - r.top) / r.height) * 100;
  }
  if (hasScreenApi) {
    $("light").hidden = false;
    var saved = android.getBrightness();
    showLight(saved > 0 ? Math.round(saved * 100) : 60);
    // El brillo se ve en vivo mientras se arrastra
    lightRail.addEventListener("pointerdown", function (e) {
      lightDragging = true;
      if (lightRail.setPointerCapture && e.pointerId !== undefined) lightRail.setPointerCapture(e.pointerId);
      lightRail.classList.add("dragging");
      setLight(lightAt(e.clientY));
      e.preventDefault();
    });
    lightRail.addEventListener("pointermove", function (e) { if (lightDragging) setLight(lightAt(e.clientY)); });
    function lightUp() { lightDragging = false; lightRail.classList.remove("dragging"); }
    lightRail.addEventListener("pointerup", lightUp);
    lightRail.addEventListener("pointercancel", lightUp);
    var current = function () { return parseInt(lightRail.getAttribute("aria-valuenow"), 10) || 60; };
    $("light-up").addEventListener("click", function () { setLight(current() + 10); });
    $("light-down").addEventListener("click", function () { setLight(current() - 10); });
    lightRail.addEventListener("keydown", function (e) {
      if (e.key === "ArrowUp") { setLight(current() + 10); e.preventDefault(); }
      if (e.key === "ArrowDown") { setLight(current() - 10); e.preventDefault(); }
    });
  }

  // La pantalla se apaga a los 2 min sin música ni toques. Android la apaga cuando pasa su propio
  // tiempo (screen_off_timeout) sin que la app la retenga, así que se retiene solo la diferencia.
  var IDLE_LIMIT = 2 * 60 * 1000;
  var lastTouch = Date.now(), keptAwake = true;
  function markActive() { lastTouch = Date.now(); updateAwake(); }
  ["pointerdown", "keydown"].forEach(function (ev) { document.addEventListener(ev, markActive, true); });
  window.srhWake = markActive;   // la app lo llama al encender la pantalla
  function updateAwake() {
    if (!hasScreenApi) return;
    var timeout = android.screenOffTimeout ? android.screenOffTimeout() : 60000;
    var hold = Math.max(0, IDLE_LIMIT - timeout);
    // De noche la música no retiene la pantalla: solo un toque reciente o el menú abierto
    var night = state.mode === "night";
    var want = (state.playing && !night) || !$("sheet").hidden || Date.now() - lastTouch < hold;
    if (want !== keptAwake) {
      keptAwake = want;
      android.setKeepAwake(want);
    }
  }
  setInterval(updateAwake, 5000);

  tick();
  render();
  refreshHealth(); refreshDevices(); refreshAudio(); refreshNowPlaying();
  setInterval(tick, 1000);
  setInterval(refreshNowPlaying, 2000);
  setInterval(refreshDevices, 10000);
  setInterval(refreshAudio, 15000);
  setInterval(refreshHealth, 30000);
  refreshBattery();
  setInterval(refreshBattery, 60000);
  refreshMode();
  setInterval(refreshMode, 20000);
})();
