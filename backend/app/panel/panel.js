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

  function api(method, path) {
    return fetch(path, { method: method, headers: { Authorization: "Bearer " + token } })
      .then(function (r) {
        if (!r.ok) {
          return r.json().catch(function () { return {}; }).then(function (b) {
            var err = new Error(b.detail || ("Error " + r.status));
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
    body.classList.toggle("idle", !hasTrack);
    $("track").classList.toggle("paused", hasTrack && !np.playing);
    $("title").textContent = hasTrack ? np.title : "";
    $("artist").textContent = hasTrack ? (np.artist || "") : "";
    showArt(hasTrack ? np.art_url : null);
  }

  // --- Controles ---
  var state = { power: null, audioHere: null, btAvailable: true, offline: false };

  function setSwitch(id, on, text) {
    var el = $(id);
    el.setAttribute("aria-pressed", on ? "true" : "false");
    $(id + "-state").textContent = text;
  }

  function render() {
    if (state.power === null) setSwitch("power", false, "Sin respuesta");
    else setSwitch("power", state.power, state.power ? "Encendidos" : "Apagados");

    if (state.audioHere === null) setSwitch("audio", false, "Desconocido");
    else if (state.audioHere) setSwitch("audio", true, "Sonando aquí");
    else setSwitch("audio", false, state.power ? "En otro equipo · tocar para traer" : "Parlantes apagados");
    $("audio").disabled = !state.btAvailable || state.audioHere === true || state.power === false;

    var notice = "";
    if (state.offline) notice = "No hay conexión con el servidor. Reintentando…";
    else if (state.power === null) notice = "Los parlantes no responden: revisa el enchufe y el Wi-Fi.";
    else if (!state.btAvailable) notice = "Cambio de audio desactivado: abre Shizuku y toca Start.";
    $("notice").textContent = notice;
    $("notice").hidden = !notice;
  }

  function flash(message) {
    $("notice").textContent = message;
    $("notice").hidden = false;
    setTimeout(render, 6000);
  }

  function busy(id, on) {
    $(id).classList.toggle("busy", on);
  }

  $("power").addEventListener("click", function () {
    busy("power", true);
    api("POST", "/devices/" + DEVICE + "/toggle")
      .then(function (d) { state.power = d.online ? d.on : null; render(); setTimeout(refreshAudio, 6000); })
      .catch(function (e) { flash("No se pudo cambiar los parlantes: " + e.message); })
      .then(function () { busy("power", false); });
  });

  $("audio").addEventListener("click", function () {
    busy("audio", true);
    api("POST", "/bluetooth/" + BT + "/connect")
      .then(function (d) { state.audioHere = d.connected; render(); })
      .catch(function () { flash("No se pudo traer el audio. Si la Mac tiene los parlantes, usa Music mode desde la Mac."); })
      .then(function () { busy("audio", false); });
  });

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
  setInterval(refreshNowPlaying, 2500);
  setInterval(refreshDevices, 10000);
  setInterval(refreshAudio, 15000);
  setInterval(refreshHealth, 30000);
})();
