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
  try { dateFmt = new Intl.DateTimeFormat("es-EC", { weekday: "long", day: "numeric", month: "long" }); }
  catch (e) { dateFmt = null; }

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function tick() {
    var now = new Date();
    $("clock").textContent = pad(now.getHours()) + ":" + pad(now.getMinutes());
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

  function dominantColor(img) {
    // Promedio de una versión diminuta de la portada, oscurecido para que no deslumbre
    try {
      var c = document.createElement("canvas");
      c.width = c.height = 16;
      var ctx = c.getContext("2d");
      ctx.drawImage(img, 0, 0, 16, 16);
      var d = ctx.getImageData(0, 0, 16, 16).data, r = 0, g = 0, b = 0, n = 0;
      for (var i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; n++; }
      var k = 0.42;
      return "rgb(" + Math.round(r / n * k) + "," + Math.round(g / n * k) + "," + Math.round(b / n * k) + ")";
    } catch (e) { return null; }
  }

  function showArt(url) {
    if (url === lastArt) return;
    lastArt = url;
    var cover = $("cover"), backdrop = document.querySelector(".backdrop");
    if (!url) {
      cover.innerHTML = "";
      backdrop.style.backgroundImage = "";
      document.documentElement.style.setProperty("--tint", "var(--night)");
      return;
    }
    var img = new Image();
    img.alt = "";
    img.onload = function () {
      cover.innerHTML = "";
      cover.appendChild(img);
      backdrop.style.backgroundImage = "url('" + url + "')";
      var color = dominantColor(img);
      if (color) document.documentElement.style.setProperty("--tint", color);
    };
    img.src = url;
  }

  function renderNowPlaying(np) {
    var hasTrack = !!(np && np.title);
    state.playing = !!(np && np.playing);
    body.classList.toggle("idle", !hasTrack);
    $("track").classList.toggle("paused", hasTrack && !np.playing);
    $("title").textContent = hasTrack ? np.title : "";
    $("artist").textContent = hasTrack ? (np.artist || "") : "";
    showArt(hasTrack ? np.art_url : null);

    var pp = $("playpause");
    pp.classList.toggle("playing", state.playing);
    pp.setAttribute("aria-label", state.playing ? "Pausar" : "Reproducir");

    if (np && typeof np.volume === "number") {
      state.volume = np.volume;
      if (!dragging) {
        $("volume").value = np.volume;
        $("volume-value").textContent = np.volume + " %";
      }
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

  var dragging = false;
  var volume = $("volume");
  volume.addEventListener("input", function () {
    dragging = true;
    $("volume-value").textContent = volume.value + " %";
  });
  volume.addEventListener("change", function () {
    dragging = false;
    command("volume", parseInt(volume.value, 10));
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
