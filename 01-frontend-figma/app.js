/* =====================================================================
   Upload Your Resume — 交互逻辑
   1) 点击 / 键盘 / 拖拽 三种方式选文件
   2) 扩展名 + 大小校验，页面内提示（不使用 alert）
   3) 未选文件点 Finish 给出引导；选中后 Finish 推进进度条
   ===================================================================== */
(function () {
  'use strict';

  var ALLOWED_EXT = ['pdf', 'doc', 'docx', 'png', 'jpg', 'jpeg'];
  var ALLOWED_MIME = [
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/png',
    'image/jpeg'
  ];
  var MAX_SIZE = 10 * 1024 * 1024; // 10 MB
  var DEFAULT_HINT =
    'Drag your resume file to this area, or click on the area to select ' +
    'the appropriate file to upload';

  var dropzone = document.getElementById('dropzone');
  var input = document.getElementById('file-input');
  var hint = document.getElementById('dz-hint');
  var meta = document.getElementById('dz-meta');
  var statusEl = document.getElementById('status');
  var btnLast = document.getElementById('btn-last');
  var btnFinish = document.getElementById('btn-finish');
  var stepsEl = document.getElementById('steps');
  var stepItems = Array.prototype.slice.call(stepsEl.querySelectorAll('.steps__item'));

  if (!dropzone || !input) { return; }

  var currentFile = null;
  var currentStep = 3;
  var dragDepth = 0;

  /* ---------------- 工具函数 ---------------- */

  function extOf(name) {
    var i = String(name).lastIndexOf('.');
    return i === -1 ? '' : String(name).slice(i + 1).toLowerCase();
  }

  function formatSize(bytes) {
    if (!bytes && bytes !== 0) { return ''; }
    if (bytes < 1024) { return bytes + ' B'; }
    if (bytes < 1024 * 1024) { return (bytes / 1024).toFixed(1) + ' KB'; }
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function setStatus(text, tone) {
    statusEl.textContent = text || '';
    statusEl.className = 'status' + (tone ? ' is-' + tone : '');
  }

  /**
   * 校验：先看扩展名，扩展名合法时再用 MIME 兜底（部分系统的 docx MIME 为空）
   */
  function validate(file) {
    var ext = extOf(file.name);
    if (!ext) {
      return { ok: false, message: '这个文件没有扩展名，无法判断类型，请上传 PDF / DOC / DOCX / PNG / JPG / JPEG。' };
    }
    if (ALLOWED_EXT.indexOf(ext) === -1) {
      return { ok: false, message: '“' + ext.toUpperCase() + '” 不是支持的文件类型，请上传 PDF / DOC / DOCX / PNG / JPG / JPEG。' };
    }
    if (file.type && ALLOWED_MIME.indexOf(file.type) === -1) {
      // 扩展名对但 MIME 可疑（例如把 .zip 改名成 .pdf）
      if (ext !== 'docx' && ext !== 'doc') {
        return { ok: false, message: '文件内容与扩展名不匹配，请确认后再上传。' };
      }
    }
    if (file.size > MAX_SIZE) {
      return { ok: false, message: '文件超过 10 MB（当前 ' + formatSize(file.size) + '），请压缩后重试。' };
    }
    if (!file.size) {
      return { ok: false, message: '这是一个空文件，请换一个文件试试。' };
    }
    return { ok: true };
  }

  /* ---------------- 视图状态 ---------------- */

  function renderEmpty() {
    dropzone.dataset.icon = 'cloud';
    dropzone.dataset.state = 'empty';
    dropzone.classList.remove('is-invalid');
    hint.hidden = false;
    hint.textContent = DEFAULT_HINT;
    meta.hidden = true;
    meta.innerHTML = '';
    input.value = '';
    currentFile = null;
  }

  function renderSelected(file) {
    dropzone.dataset.icon = 'file';
    dropzone.dataset.state = 'filled';
    dropzone.classList.remove('is-invalid');
    hint.hidden = true;
    meta.hidden = false;
    meta.innerHTML = '';

    var nameEl = document.createElement('span');
    nameEl.className = 'dropzone__name';
    nameEl.textContent = file.name;

    var sizeEl = document.createElement('span');
    sizeEl.className = 'dropzone__size';
    sizeEl.textContent = formatSize(file.size) + ' · 已就绪，点击可重新选择';

    meta.appendChild(nameEl);
    meta.appendChild(sizeEl);
  }

  function renderSteps() {
    stepItems.forEach(function (item, index) {
      var n = index + 1;
      item.classList.toggle('is-done', n < currentStep);
      item.classList.toggle('is-current', n === currentStep);
      if (n === currentStep) {
        item.setAttribute('aria-current', 'step');
      } else {
        item.removeAttribute('aria-current');
      }
    });
    stepsEl.classList.toggle('is-complete', currentStep > stepItems.length);
  }

  /* ---------------- 文件处理 ---------------- */

  function acceptFile(file) {
    var result = validate(file);
    if (!result.ok) {
      currentFile = null;
      renderEmpty();
      dropzone.classList.add('is-invalid');
      setStatus(result.message, 'error');
      input.value = '';
      return false;
    }

    currentFile = file;
    renderSelected(file);
    setStatus('已选择 ' + file.name + '（' + formatSize(file.size) + '），确认无误后点击 Finish。', 'success');
    if (btnFinish.textContent !== 'Finish') { btnFinish.textContent = 'Finish'; }
    input.value = '';
    return true;
  }

  function handleFiles(fileList) {
    if (!fileList || !fileList.length) { return; }
    if (fileList.length > 1) {
      setStatus('一次只能上传 1 个文件，已取第一个：' + fileList[0].name, 'info');
    }
    acceptFile(fileList[0]);
  }

  /* ---------------- 事件：点击 / 键盘 ---------------- */

  // label[for] 已原生触发文件选择框；键盘操作在此补齐 Enter / Space
  dropzone.addEventListener('click', function () {
    dropzone.classList.remove('is-invalid');
  });

  dropzone.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
      event.preventDefault();
      input.click();
    }
  });

  input.addEventListener('change', function () {
    handleFiles(input.files);
  });

  /* ---------------- 事件：拖拽 ---------------- */

  ['dragenter', 'dragover'].forEach(function (type) {
    dropzone.addEventListener(type, function (event) {
      event.preventDefault();
      event.stopPropagation();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = 'copy';
      }
      if (type === 'dragenter') { dragDepth += 1; }
      dropzone.classList.remove('is-invalid');
      dropzone.classList.add('is-dragover');
    });
  });

  dropzone.addEventListener('dragleave', function (event) {
    event.preventDefault();
    event.stopPropagation();
    dragDepth -= 1;
    if (dragDepth <= 0) {
      dragDepth = 0;
      dropzone.classList.remove('is-dragover');
    }
  });

  dropzone.addEventListener('drop', function (event) {
    event.preventDefault();
    event.stopPropagation();
    dragDepth = 0;
    dropzone.classList.remove('is-dragover');
    if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length) {
      handleFiles(event.dataTransfer.files);
    }
  });

  // 防止文件被拖到页面其它位置时浏览器直接打开它
  ['dragover', 'drop'].forEach(function (type) {
    window.addEventListener(type, function (event) {
      if (!dropzone.contains(event.target)) { event.preventDefault(); }
    });
  });

  /* ---------------- 事件：按钮 ---------------- */

  btnFinish.addEventListener('click', function () {
    if (!currentFile) {
      dropzone.classList.add('is-invalid');
      dropzone.classList.remove('is-shaking');
      // 强制重排以便重复触发动画
      void dropzone.offsetWidth;
      dropzone.classList.add('is-shaking');
      setStatus('还没有选择简历文件，请先点击虚线区域选择或拖入一个文件。', 'error');
      dropzone.focus();
      return;
    }

    currentStep = stepItems.length + 1;
    renderSteps();
    setStatus('已提交 “' + currentFile.name + '”，我们会在解析完成后通知你。', 'success');
    btnFinish.textContent = 'Submitted';
    btnFinish.disabled = false;
  });

  btnLast.addEventListener('click', function () {
    currentStep = 2;
    renderSteps();
    setStatus('已回到上一步，你可以继续修改简历文件。', 'info');
    btnFinish.textContent = 'Finish';
  });

  /* ---------------- 初始化 ---------------- */
  renderEmpty();
  renderSteps();
  setStatus('', '');
})();
