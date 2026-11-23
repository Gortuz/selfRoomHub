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
    body.classList.toggle("night", h >= NIGHT_FROM || h < NIGHT_TO);
  }

  // --- Estado ---
  var state = {
    power: null,        // true / false / null (sin respuesta)
    audioHere: null,    // el servidor tiene el parlante Bluetooth
    btAvailable: true,  // Shizuku activo
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

    var notice = "";
    if (state.offline) notice = "No hay conexión con el servidor. Reintentando…";
    else if (state.power === null) notice = "Los parlantes no responden: revisa el enchufe y el Wi-Fi.";
    else if (!state.btAvailable) notice = "Cambio de audio desactivado: abre Shizuku y toca Start.";
    $("notice").textContent = notice;
    $("notice").hidden = !notice;

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
      .then(function (d) { state.power = d.online ? d.on : null; state.offline = false; })
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

  function refreshHealth() {
    fetch("/health").then(function (r) { return r.json(); })
      .then(function (h) { state.btAvailable = h.bluetooth !== "unavailable"; state.offline = false; })
      .catch(function () { state.offline = true; })
      .then(render);
  }

  tick();
  render();
  refreshHealth(); refreshDevices(); refreshAudio(); refreshNowPlaying();
  setInterval(tick, 1000);
  setInterval(refreshNowPlaying, 2000);
  setInterval(refreshDevices, 10000);
  setInterval(refreshAudio, 15000);
  setInterval(refreshHealth, 30000);
})();
