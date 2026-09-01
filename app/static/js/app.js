(function () {

  const STORAGE_KEY = "siteAssessorSession";

  const stepAuth = document.getElementById("stepAuth");
  const stepProfile = document.getElementById("stepProfile");
  const stepForm = document.getElementById("stepForm");
  const headerUser = document.getElementById("headerUser");
  const avatarInitial = document.getElementById("avatarInitial");
  const dropdownUserName = document.getElementById("dropdownUserName");
  const userDropdown = document.getElementById("userDropdown");
  const loginForm = document.getElementById("loginForm");
  const registerForm = document.getElementById("registerForm");
  const authError = document.getElementById("authError");
  const profileError = document.getElementById("profileError");
  const profileSuccess = document.getElementById("profileSuccess");
  const profileUsername = document.getElementById("profileUsername");
  const profileWebKeyHint = document.getElementById("profileWebKeyHint");
  const profileJsKeyHint = document.getElementById("profileJsKeyHint");
  const profileWebKeyInput = document.getElementById("profileWebKey");
  const profileJsKeyInput = document.getElementById("profileJsKey");
  const profileSecurityCodeInput = document.getElementById("profileSecurityCode");

  const amapKeyHidden = document.getElementById("amap_key");
  const keyModeHint = document.getElementById("keyModeHint");
  const mapHint = document.getElementById("mapHint");
  const mapPlaceholder = document.getElementById("mapPlaceholder");
  const mapCanvas = document.getElementById("mapCanvas");
  const searchStatus = document.getElementById("searchStatus");
  const btnSearchPlace = document.getElementById("btnSearchPlace");
  const form = document.getElementById("generateForm");
  const lngInput = document.getElementById("lng");
  const latInput = document.getElementById("lat");
  const lngDisplay = document.getElementById("lngDisplay");
  const latDisplay = document.getElementById("latDisplay");
  const demoIdInput = document.getElementById("demo_id");
  const errorBox = document.getElementById("errorBox");
  const loading = document.getElementById("loading");
  const placeName = document.getElementById("place_name");
  const cityInput = document.getElementById("city");
  const tipsBox = document.getElementById("tips");
  const demoVideoCard = document.getElementById("demoVideoCard");
  const usageDemoVideo = document.getElementById("usageDemoVideo");

  let currentUser = null;
  let useAccountKeys = false;
  let demoMode = false;
  let amapWebKey = "";
  let amapJsKey = "";
  let amapSecurityCode = "";
  let map = null;
  let marker = null;
  let mapReady = false;

  document.getElementById("tabLogin").addEventListener("click", () => switchAuthTab("login"));
  document.getElementById("tabRegister").addEventListener("click", () => switchAuthTab("register"));
  loginForm.addEventListener("submit", onLoginSubmit);
  registerForm.addEventListener("submit", onRegisterSubmit);
  document.getElementById("btnSkipDemoAuth").addEventListener("click", function () {
    onSkipToDemo();
    startDemoReport();
  });
  document.getElementById("btnSaveKeys").addEventListener("click", onSaveKeys);
  document.getElementById("btnProfileToAnalyze").addEventListener("click", onProfileToAnalyze);
  document.getElementById("btnBackProfile").addEventListener("click", showProfile);
  document.getElementById("btnUserMenu").addEventListener("click", function (e) {
    e.stopPropagation();
    toggleUserDropdown();
  });
  document.getElementById("btnOpenProfile").addEventListener("click", function () {
    userDropdown.classList.add("hidden");
    showProfile();
  });
  document.getElementById("btnGoAnalyze").addEventListener("click", function () {
    userDropdown.classList.add("hidden");
    onProfileToAnalyze();
  });
  document.getElementById("btnLogout").addEventListener("click", onLogout);
  document.addEventListener("click", function (e) {
    if (!document.getElementById("headerUser").contains(e.target)) {
      userDropdown.classList.add("hidden");
      document.getElementById("btnUserMenu").setAttribute("aria-expanded", "false");
    }
  });
  btnSearchPlace.addEventListener("click", searchPlace);
  placeName.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      searchPlace();
    }
  });
  placeName.addEventListener("input", function () {
    demoIdInput.value = "";
  });
  document.getElementById("demoA").addEventListener("click", function () {
    startDemoReport();
  });
  form.addEventListener("submit", onSubmit);

  function apiFetch(url, options) {
    options = options || {};
    options.credentials = "same-origin";
    return fetch(url, options);
  }

  const urlParams = new URLSearchParams(window.location.search);
  initApp();

  async function initApp() {
    try {
      const resp = await apiFetch("/api/auth/me");
      const data = await resp.json();
      if (data.logged_in && data.user) {
        setCurrentUser(data.user);
        if (urlParams.get("step") === "2" && sessionStorage.getItem(STORAGE_KEY)) {
          restoreStep2FromSession();
          return;
        }
        if (data.user.has_amap_keys) {
          applyUserKeys(data.user);
          showStep2("已加载您保存的高德 Key，可直接检索地点。");
          loadAmapAndInit();
        } else {
          showProfile("注册成功！请先在个人中心填写高德 Key。");
        }
        return;
      }
    } catch (err) {
      /* ignore */
    }
    showAuth();
  }

  function switchAuthTab(tab) {
    document.querySelectorAll(".auth-tab").forEach(function (el) {
      el.classList.toggle("active", el.dataset.tab === tab);
    });
    loginForm.classList.toggle("hidden", tab !== "login");
    registerForm.classList.toggle("hidden", tab !== "register");
    hideAuthError();
  }

  function setCurrentUser(user) {
    currentUser = user;
    headerUser.classList.remove("hidden");
    const name = user.display_name || user.username || "U";
    avatarInitial.textContent = name.charAt(0).toUpperCase();
    dropdownUserName.textContent = name;
    profileUsername.textContent = user.username;
    profileWebKeyHint.textContent = user.amap_web_key_masked
      ? "已保存 Web Key：" + user.amap_web_key_masked + "（留空输入框则不修改）"
      : "尚未保存 Web 服务 Key";
    profileJsKeyHint.textContent = user.amap_js_key_masked
      ? "已保存 JS Key：" + user.amap_js_key_masked
      : "尚未保存 JS API Key";
  }

  function applyUserKeys(user) {
    useAccountKeys = true;
    demoMode = false;
    amapWebKey = "";
    amapJsKey = user.amap_js_key || "";
    amapSecurityCode = user.amap_security_code || "";
    amapKeyHidden.value = "";
    saveSession();
  }

  function syncDemoVideo() {
    if (!demoVideoCard || !usageDemoVideo) return;
    const show = !stepAuth.classList.contains("hidden") || !stepForm.classList.contains("hidden");
    demoVideoCard.classList.toggle("hidden", !show);
    if (show) {
      usageDemoVideo.currentTime = 0;
      usageDemoVideo.play().catch(function () { /* autoplay blocked */ });
    } else {
      usageDemoVideo.pause();
    }
  }

  function showAuth() {
    stepAuth.classList.remove("hidden");
    stepProfile.classList.add("hidden");
    stepForm.classList.add("hidden");
    headerUser.classList.add("hidden");
    currentUser = null;
    useAccountKeys = false;
    syncDemoVideo();
  }

  function showProfile(message) {
    if (!currentUser) {
      showAuth();
      return;
    }
    stepAuth.classList.add("hidden");
    stepProfile.classList.remove("hidden");
    stepForm.classList.add("hidden");
    profileError.classList.add("hidden");
    profileSuccess.classList.add("hidden");
    profileWebKeyInput.value = "";
    profileJsKeyInput.value = currentUser.has_amap_keys ? "" : "";
    profileSecurityCodeInput.value = "";
    destroyMap();
    if (message) {
      profileSuccess.textContent = message;
      profileSuccess.classList.remove("hidden");
    }
    syncDemoVideo();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function hideAuthError() {
    authError.classList.add("hidden");
    authError.textContent = "";
  }

  function showAuthError(msg) {
    authError.textContent = msg;
    authError.classList.remove("hidden");
  }

  async function onLoginSubmit(e) {
    e.preventDefault();
    hideAuthError();
    const body = new FormData();
    body.append("username", document.getElementById("loginUsername").value.trim());
    body.append("password", document.getElementById("loginPassword").value);
    try {
      const resp = await apiFetch("/api/auth/login", { method: "POST", body: body });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "登录失败");
      setCurrentUser(data.user);
      if (data.user.has_amap_keys) {
        applyUserKeys(data.user);
        showStep2("登录成功，已加载您保存的高德 Key。");
        loadAmapAndInit();
      } else {
        showProfile("登录成功！请先在个人中心填写高德 Key。");
      }
    } catch (err) {
      showAuthError(err.message || "登录失败");
    }
  }

  async function onRegisterSubmit(e) {
    e.preventDefault();
    hideAuthError();
    const pwd = document.getElementById("registerPassword").value;
    const pwd2 = document.getElementById("registerPassword2").value;
    if (pwd !== pwd2) {
      showAuthError("两次输入的密码不一致");
      return;
    }
    const body = new FormData();
    body.append("username", document.getElementById("registerUsername").value.trim());
    body.append("password", pwd);
    body.append("display_name", document.getElementById("registerDisplayName").value.trim());
    try {
      const resp = await apiFetch("/api/auth/register", { method: "POST", body: body });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "注册失败");
      setCurrentUser(data.user);
      showProfile("注册成功！请填写高德 Key 并保存。");
    } catch (err) {
      showAuthError(err.message || "注册失败");
    }
  }

  async function onSaveKeys() {
    profileError.classList.add("hidden");
    profileSuccess.classList.add("hidden");
    const web = profileWebKeyInput.value.trim();
    const js = profileJsKeyInput.value.trim();
    const sec = profileSecurityCodeInput.value.trim();
    if (!currentUser.has_amap_keys && (!web || !js)) {
      profileError.textContent = "首次保存须完整填写 Web 服务 Key 与 JS API Key";
      profileError.classList.remove("hidden");
      return;
    }
    const body = new FormData();
    body.append("amap_web_key", web || "__keep__");
    body.append("amap_js_key", js || "__keep__");
    body.append("amap_security_code", sec || (currentUser.has_security_code ? "__keep__" : ""));
    try {
      const resp = await apiFetch("/api/auth/keys", { method: "POST", body: body });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "保存失败");
      setCurrentUser(data.user);
      applyUserKeys(data.user);
      profileWebKeyInput.value = "";
      profileJsKeyInput.value = "";
      profileSecurityCodeInput.value = "";
      profileSuccess.textContent = "Key 已保存，下次登录将自动使用。";
      profileSuccess.classList.remove("hidden");
    } catch (err) {
      profileError.textContent = err.message || "保存失败";
      profileError.classList.remove("hidden");
    }
  }

  function onProfileToAnalyze() {
    if (!currentUser) {
      showAuth();
      return;
    }
    if (!currentUser.has_amap_keys) {
      profileError.textContent = "请先保存高德 Key";
      profileError.classList.remove("hidden");
      return;
    }
    showStep2("地点名点「检索」选位置；也可在地图上点击/拖拽微调落点。");
    loadAmapAndInit();
  }

  async function onLogout() {
    userDropdown.classList.add("hidden");
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch (err) {
      /* ignore */
    }
    sessionStorage.removeItem(STORAGE_KEY);
    demoMode = false;
    useAccountKeys = false;
    amapWebKey = "";
    amapJsKey = "";
    amapSecurityCode = "";
    destroyMap();
    showAuth();
  }

  function toggleUserDropdown() {
    const open = userDropdown.classList.toggle("hidden") === false;
    document.getElementById("btnUserMenu").setAttribute("aria-expanded", open ? "true" : "false");
  }

  function saveSession() {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
      demoMode: demoMode,
      useAccountKeys: useAccountKeys,
      amapWebKey: amapWebKey,
      amapJsKey: amapJsKey,
      amapSecurityCode: amapSecurityCode,
    }));
  }

  function restoreStep2FromSession() {
    let saved = null;
    try {
      saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    } catch (err) {
      saved = null;
    }
    if (!saved) return;
    if (saved.demoMode) {
      onSkipToDemo();
      return;
    }
    if (currentUser && currentUser.has_amap_keys) {
      applyUserKeys(currentUser);
      showStep2("已恢复上次会话，可直接检索地点。");
      loadAmapAndInit();
    }
  }

  function onSkipToDemo() {
    demoMode = true;
    useAccountKeys = false;
    amapWebKey = "";
    amapJsKey = "";
    amapSecurityCode = "";
    amapKeyHidden.value = "";
    saveSession();
    showStep2("演示模式：无需 Key，正在生成演示报告…");
    showDemoMapPlaceholder();
    btnSearchPlace.disabled = true;
  }

  function showStep2(hint) {
    stepAuth.classList.add("hidden");
    stepProfile.classList.add("hidden");
    stepForm.classList.remove("hidden");
    keyModeHint.textContent = hint;
    btnSearchPlace.disabled = demoMode;
    syncDemoVideo();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }



  function showSearchStatus(msg, isError) {

    searchStatus.textContent = msg;

    searchStatus.classList.remove("hidden", "error");

    if (isError) searchStatus.classList.add("error");

  }



  function hideSearchStatus() {

    searchStatus.classList.add("hidden");

    searchStatus.textContent = "";

  }



  function resetAmapSdk() {

    const script = document.getElementById("amap-sdk");

    if (script) script.remove();

    try {

      delete window.AMap;

    } catch (err) {

      window.AMap = undefined;

    }

  }



  function loadAmapScript(key, securityCode) {

    return new Promise((resolve, reject) => {

      resetAmapSdk();

      if (securityCode) {

        window._AMapSecurityConfig = { securityJsCode: securityCode };

      } else {

        try {

          delete window._AMapSecurityConfig;

        } catch (err) {

          window._AMapSecurityConfig = undefined;

        }

      }

      const script = document.createElement("script");

      script.id = "amap-sdk";

      script.src = "https://webapi.amap.com/maps?v=2.0&key=" + encodeURIComponent(key);

      script.onload = () => resolve();

      script.onerror = () => reject(new Error("高德地图 JS 加载失败"));

      document.head.appendChild(script);

    });

  }



  async function loadAmapAndInit() {

    mapPlaceholder.classList.add("hidden");

    mapCanvas.classList.remove("hidden");

    mapHint.textContent = "正在加载高德地图…";



    try {

      await loadAmapScript(amapJsKey, amapSecurityCode);

      initMap();

      mapReady = true;

      mapHint.textContent = "点选检索结果后地图自动定位；可拖拽标记或点击地图微调落点";

    } catch (err) {

      mapReady = false;

      var secHint = amapSecurityCode

        ? ""

        : " 若控制台已启用安全密钥，请在个人中心填写 securityJsCode。";

      mapHint.textContent = "地图加载失败：" + err.message + secHint + " 地点检索仍可用 Web 服务 Key 正常进行。";

    }

  }



  function initMap() {

    if (!window.AMap) return;

    destroyMap();

    const lng = parseFloat(lngInput.value) || 121.473701;

    const lat = parseFloat(latInput.value) || 31.230416;



    map = new AMap.Map("mapCanvas", {

      zoom: 16,

      center: [lng, lat],

      viewMode: "2D",

    });



    marker = new AMap.Marker({

      position: [lng, lat],

      draggable: true,

      cursor: "move",

    });

    map.add(marker);



    marker.on("dragend", function (e) {

      const pos = e.target.getPosition();

      setCoords(pos.getLng(), pos.getLat());

      demoIdInput.value = "";

      demoMode = false;

    });



    map.on("click", function (e) {

      const lnglat = e.lnglat;

      marker.setPosition(lnglat);

      setCoords(lnglat.getLng(), lnglat.getLat());

      demoIdInput.value = "";

      demoMode = false;

    });



    setTimeout(function () {

      if (map) map.resize();

    }, 200);

  }



  async function searchPlace() {

    hideSearchStatus();

    tipsBox.classList.remove("show");

    tipsBox.innerHTML = "";



    if (demoMode) {

      showSearchStatus("演示模式请直接点「演示点」", true);

      return;

    }



    const kw = placeName.value.trim();

    const city = cityInput.value.trim();

    if (!kw) {

      showSearchStatus("请先输入地点名", true);

      return;

    }



    btnSearchPlace.disabled = true;

    btnSearchPlace.textContent = "检索中…";

    showSearchStatus("正在检索「" + kw + "」…");



    try {

      let tips = [];

      let errMsg = "";

      const canUseServer = useAccountKeys || (amapWebKey && amapWebKey !== "server");



      function tipsHaveLocation(list) {

        return list.some(function (t) {

          return t.location && String(t.location).indexOf(",") >= 0;

        });

      }



      if (canUseServer) {

        showSearchStatus("正在通过 Web 服务 Key 检索…");

        const serverResult = await searchWithServer(kw, city);

        if (serverResult.tips && serverResult.tips.length) {

          tips = serverResult.tips;

          errMsg = "";

        } else {

          errMsg = serverResult.error || "";

        }

      }



      if ((!tips.length || !tipsHaveLocation(tips)) && window.AMap) {

        showSearchStatus("正在通过高德地图 JS 检索…");

        const jsTips = await searchWithAmapJs(kw, city);

        if (jsTips.length) {

          tips = jsTips;

          errMsg = "";

        }

      }



      if ((!tips.length || !tipsHaveLocation(tips)) && canUseServer && !errMsg) {

        const serverRetry = await searchWithServer(kw, city);

        if (serverRetry.tips && serverRetry.tips.length) {

          tips = serverRetry.tips;

          errMsg = "";

        } else {

          errMsg = serverRetry.error || errMsg;

        }

      }



      if (!tips.length) {

        var hint = "地图上能看到店名，只说明 JS Key 正常；";

        if (!canUseServer) {
          hint += "请在个人中心配置 Web 服务 Key。";

        } else if (errMsg) {

          hint += "Web 服务 Key 报错：" + errMsg + "。请确认 Key 类型为「Web 服务」且已开通搜索类接口。";

        } else {

          hint += "请换更完整的关键词（如加区名/路名），或检查 Web 服务 Key。";

        }

        showSearchStatus("未找到可落点的匹配结果。" + hint, true);

        return;

      }



      renderTipsDropdown(tips, kw);

      showSearchStatus("共 " + tips.length + " 条结果，请点击下方列表确认位置");

    } catch (err) {

      showSearchStatus("检索失败：" + (err.message || "请检查网络"), true);

    } finally {

      btnSearchPlace.disabled = demoMode;

      btnSearchPlace.textContent = "检索";

    }

  }



  function searchWithAmapJs(keyword, city) {

    return new Promise(function (resolve) {

      if (!window.AMap) {

        resolve([]);

        return;

      }

      AMap.plugin(["AMap.PlaceSearch"], function () {

        const cityName = (city || "").replace(/市$/, "") || "全国";

        const placeSearch = new AMap.PlaceSearch({

          pageSize: 15,

          city: cityName,

          citylimit: !!city,

          extensions: "base",

        });

        placeSearch.search(keyword, function (status, result) {

          if (status !== "complete" || !result.poiList || !result.poiList.pois) {

            if (city) {

              const ps2 = new AMap.PlaceSearch({ pageSize: 15, city: cityName, citylimit: false });

              ps2.search(keyword, function (st2, res2) {

                resolve(extractAmapPois(st2, res2));

              });

              return;

            }

            resolve([]);

            return;

          }

          resolve(extractAmapPois(status, result));

        });

      });

    });

  }



  function extractAmapPois(status, result) {

    if (status !== "complete" || !result.poiList || !result.poiList.pois) {

      return [];

    }

    return result.poiList.pois

      .filter(function (poi) { return poi.location; })

      .map(function (poi) {

        return {

          name: poi.name || "",

          address: poi.address || poi.cityname || poi.adname || "",

          location: poi.location.lng + "," + poi.location.lat,

        };

      });

  }



  async function searchWithServer(kw, city) {

    let url = "/api/tips?keywords=" + encodeURIComponent(kw) +

      "&city=" + encodeURIComponent(city);

    if (amapWebKey && amapWebKey !== "server" && !useAccountKeys) {
      url += "&amap_key=" + encodeURIComponent(amapWebKey);
    }

    const resp = await apiFetch(url);

    let data = {};

    try {

      data = await resp.json();

    } catch (err) {

      return { tips: [], error: "检索接口返回异常（HTTP " + resp.status + "）" };

    }

    if (!resp.ok) {

      return {

        tips: [],

        error: data.error || data.detail || ("检索失败（HTTP " + resp.status + "）"),

      };

    }

    if (Array.isArray(data)) {

      return { tips: data, error: "" };

    }

    return { tips: data.tips || [], error: data.error || "" };

  }



  function renderTipsDropdown(tips, keyword) {

    tipsBox.innerHTML = "";

    const title = document.createElement("div");

    title.className = "tips-dropdown-title";

    title.textContent = "「" + keyword + "」检索结果（请点击确认）";

    tipsBox.appendChild(title);



    tips.forEach(function (t) {

      const div = document.createElement("div");

      div.className = "tip-item";

      div.setAttribute("role", "option");

      const name = t.name || "未命名";

      const addr = t.address || "地址不详";

      div.innerHTML = "<strong>" + escapeHtml(name) + "</strong><span>" + escapeHtml(addr) + "</span>";

      div.addEventListener("click", function () {

        selectTip(t);

      });

      tipsBox.appendChild(div);

    });

    tipsBox.classList.add("show");

  }



  function selectTip(t) {

    placeName.value = t.name || "";

    document.getElementById("address").value = t.address || t.name || "";

    demoIdInput.value = "";

    tipsBox.classList.remove("show");

    showSearchStatus("已选择：「" + (t.name || "") + "」");



    if (t.location) {

      const parts = t.location.split(",");

      const lng = parseFloat(parts[0]);

      const lat = parseFloat(parts[1]);

      if (!isNaN(lng) && !isNaN(lat)) {

        setCoords(lng, lat);

        if (map && marker) {

          map.setCenter([lng, lat]);

          marker.setPosition([lng, lat]);

          map.setZoom(17);

          setTimeout(function () {

            if (map) map.resize();

          }, 100);

        }

      }

    }

  }



  function escapeHtml(s) {

    return String(s)

      .replace(/&/g, "&amp;")

      .replace(/</g, "&lt;")

      .replace(/>/g, "&gt;")

      .replace(/"/g, "&quot;");

  }



  function showDemoMapPlaceholder() {

    mapReady = false;

    destroyMap();

    mapCanvas.classList.add("hidden");

    mapPlaceholder.classList.remove("hidden");

    mapHint.textContent = "演示模式无高德地图界面；坐标随演示点预设。";

  }



  function destroyMap() {

    if (map) {

      map.destroy();

      map = null;

      marker = null;

    }

    mapReady = false;

  }



  function setCoords(lng, lat) {

    lngInput.value = Number(lng).toFixed(6);

    latInput.value = Number(lat).toFixed(6);

    lngDisplay.textContent = lngInput.value;

    latDisplay.textContent = latInput.value;

  }



  function loadDemo(id, lng, lat, label) {

    demoMode = true;

    demoIdInput.value = id;

    amapKeyHidden.value = "";

    placeName.value = label;

    document.getElementById("address").value = "";

    tipsBox.classList.remove("show");

    hideSearchStatus();

    setCoords(lng, lat);

    if (map && marker) {

      map.setCenter([lng, lat]);

      marker.setPosition([lng, lat]);

      map.setZoom(15);

    }

  }



  function startDemoReport() {
    onSkipToDemo();
    loadDemo("demo_a", 121.473701, 31.230416, "地图选点");
    document.getElementById("city").value = "上海市";
    const rentInput = document.querySelector('[name="rent"]');
    const revenueInput = document.querySelector('[name="revenue"]');
    const brandSelect = document.getElementById("brand_positioning");
    if (rentInput) rentInput.value = "5000";
    if (revenueInput) revenueInput.value = "20000";
    if (brandSelect) brandSelect.value = "";
    generateReport();
  }



  async function onSubmit(e) {

    e.preventDefault();

    generateReport();

  }



  async function generateReport() {

    errorBox.classList.add("hidden");



    if (!demoIdInput.value && !useAccountKeys && !amapKeyHidden.value) {
      errorBox.textContent = "查真实地点须先登录并在个人中心配置高德 Key，或选择演示点";
      errorBox.classList.remove("hidden");
      return;
    }

    if (!demoIdInput.value) {
      amapKeyHidden.value = "";
    }



    if (!demoMode) {
      demoIdInput.value = "";
    }

    saveSession();

    loading.classList.remove("hidden");

    const btn = document.getElementById("submitBtn");
    const demoBtn = document.getElementById("demoA");

    btn.disabled = true;
    if (demoBtn) demoBtn.disabled = true;

    try {

      const resp = await apiFetch("/api/generate", { method: "POST", body: new FormData(form) });

      let data = {};

      try {

        data = await resp.json();

      } catch (err) {

        /* non-json */

      }

      if (!resp.ok) {

        throw new Error(data.detail || ("生成失败（HTTP " + resp.status + "）"));

      }

      if (data.result && data.report_id) {
        try {
          sessionStorage.setItem("report:" + data.report_id, JSON.stringify(data.result));
        } catch (err) {
          /* quota exceeded — server may still have the file */
        }
      }

      window.location.href = "/report/" + data.report_id;

    } catch (err) {

      errorBox.textContent = err.message;

      errorBox.classList.remove("hidden");

    } finally {

      loading.classList.add("hidden");

      btn.disabled = false;
      if (demoBtn) demoBtn.disabled = false;

    }

  }

})();

