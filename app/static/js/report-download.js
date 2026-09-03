(function () {
  var reportId = window.__REPORT_ID__;
  if (!reportId) return;

  var storageKey = "report:" + reportId;
  var raw = sessionStorage.getItem(storageKey);
  if (!raw) return;

  var result;
  try {
    result = JSON.parse(raw);
  } catch (err) {
    return;
  }

  function downloadBlob(blob, filename) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  function svgToPngBlob(svgText) {
    return new Promise(function (resolve, reject) {
      var svg = svgText;
      if (svg.indexOf("xmlns") < 0) {
        svg = svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ');
      }
      var img = new Image();
      var url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
      img.onload = function () {
        var w = img.naturalWidth || 1210;
        var h = img.naturalHeight || 1092;
        var canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        canvas.getContext("2d").drawImage(img, 0, 0);
        URL.revokeObjectURL(url);
        canvas.toBlob(function (blob) {
          if (blob) resolve(blob);
          else reject(new Error("PNG 转换失败"));
        }, "image/png");
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("分析图 SVG 加载失败"));
      };
      img.src = url;
    });
  }

  function blobToBase64(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        resolve(String(reader.result).split(",")[1] || "");
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  document.querySelectorAll(".download-links a").forEach(function (link) {
    link.addEventListener("click", function (e) {
      e.preventDefault();
      var href = link.getAttribute("href") || "";
      var type = "svg";
      if (href.indexOf("/docx") >= 0 || href.indexOf("/word") >= 0) type = "docx";
      else if (href.indexOf("/png") >= 0) type = "png";

      var embedded = result.embedded_assets || {};
      var oldText = link.textContent;
      link.textContent = "准备中…";
      link.style.pointerEvents = "none";

      (async function () {
        try {
          if (type === "svg") {
            if (!embedded.analysis_svg) throw new Error("分析图 SVG 不可用，请重新生成报告");
            downloadBlob(new Blob([embedded.analysis_svg], { type: "image/svg+xml" }), "analysis_" + reportId + ".svg");
            return;
          }
          if (type === "png") {
            var pngBlob;
            if (embedded.analysis_png_b64) {
              var bin = atob(embedded.analysis_png_b64);
              var arr = new Uint8Array(bin.length);
              for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
              pngBlob = new Blob([arr], { type: "image/png" });
            } else if (embedded.analysis_svg) {
              pngBlob = await svgToPngBlob(embedded.analysis_svg);
            } else {
              throw new Error("分析图不可用，请重新生成报告");
            }
            downloadBlob(pngBlob, "analysis_" + reportId + ".png");
            return;
          }
          if (type === "docx") {
            var pngB64 = embedded.analysis_png_b64 || "";
            if (!pngB64 && embedded.analysis_svg) {
              pngB64 = await blobToBase64(await svgToPngBlob(embedded.analysis_svg));
            }
            var resp = await fetch("/api/download-export", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                report_id: reportId,
                result: result,
                file_type: "docx",
                png_b64: pngB64,
              }),
            });
            if (!resp.ok) {
              var errData = {};
              try { errData = await resp.json(); } catch (ignore) {}
              throw new Error(errData.detail || "Word 导出失败");
            }
            downloadBlob(await resp.blob(), "report_" + reportId + ".docx");
          }
        } catch (err) {
          alert(err.message || "下载失败");
        } finally {
          link.textContent = oldText;
          link.style.pointerEvents = "";
        }
      })();
    });
  });
})();
