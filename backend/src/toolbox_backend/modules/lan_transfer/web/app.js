/**
 * 局域网投送浏览器页面脚本。
 * 功能描述：填充会话状态，逐个上传所选文件并显示进度与结果，展示待取件清单。
 */
;(function () {
  var errorNode = document.getElementById('passphrase-error')
  if (errorNode && window.location.search.indexOf('error=1') !== -1) {
    errorNode.hidden = false
  }

  var deviceNode = document.getElementById('device-name')
  if (!deviceNode) return

  var hintNode = document.getElementById('session-hint')
  var inputNode = document.getElementById('upload-input')
  var listNode = document.getElementById('upload-list')
  var filesNode = document.getElementById('files-list')
  var filesHintNode = document.getElementById('files-hint')
  var uploading = false

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B'
    var units = ['KB', 'MB', 'GB', 'TB']
    var value = bytes / 1024
    var index = 0
    while (value >= 1024 && index < units.length - 1) {
      value = value / 1024
      index += 1
    }
    return value.toFixed(1) + ' ' + units[index]
  }

  function formatRemaining(seconds) {
    if (seconds <= 0) return '会话即将结束'
    var minutes = Math.floor(seconds / 60)
    if (minutes <= 0) return '会话剩余不到 1 分钟'
    return '会话剩余约 ' + minutes + ' 分钟'
  }

  function refreshSession() {
    fetch('/api/session', { headers: { Accept: 'application/json' } })
      .then(function (response) {
        if (!response.ok) throw new Error('session unavailable')
        return response.json()
      })
      .then(function (info) {
        deviceNode.textContent = info.device_name || '已连接'
        if (hintNode) {
          hintNode.textContent =
            '已连接到电脑端投送会话，' + formatRemaining(info.remaining_seconds)
        }
      })
      .catch(function () {
        if (hintNode) hintNode.textContent = '会话已结束，请在电脑端重新开启投送。'
      })
  }

  /** 展示电脑端选中的待取件文件；逐文件真实链接在移动端浏览器上最可靠。 */
  function refreshFiles() {
    if (!filesNode) return
    fetch('/api/files', { headers: { Accept: 'application/json' } })
      .then(function (response) {
        if (!response.ok) throw new Error('files unavailable')
        return response.json()
      })
      .then(function (payload) {
        var files = payload.files || []
        filesNode.textContent = ''
        if (!files.length) {
          filesNode.hidden = true
          if (filesHintNode) filesHintNode.textContent = '电脑端还没有选择要发送的文件。'
          return
        }
        files.forEach(function (file) {
          var row = document.createElement('li')
          row.className = 'file-item' + (file.available ? '' : ' file-item-missing')

          if (file.available) {
            var link = document.createElement('a')
            link.className = 'file-link'
            link.href = '/download/' + encodeURIComponent(file.id)
            link.setAttribute('download', file.name)
            link.textContent = file.name
            row.appendChild(link)
          } else {
            var name = document.createElement('span')
            name.className = 'file-name'
            name.textContent = file.name
            row.appendChild(name)
          }

          var size = document.createElement('span')
          size.className = 'file-size'
          size.textContent = file.available ? formatSize(file.size_bytes) : '文件已不可用'
          row.appendChild(size)
          filesNode.appendChild(row)
        })
        filesNode.hidden = false
        if (filesHintNode) {
          filesHintNode.textContent =
            '共 ' + files.length + ' 个文件，点击文件名逐个下载。'
        }
      })
      .catch(function () {
        filesNode.hidden = true
        if (filesHintNode) filesHintNode.textContent = '会话已结束，请在电脑端重新开启投送。'
      })
  }

  /** 为单个上传文件创建一行状态，返回需要后续更新的节点。 */
  function createRow(file) {
    var row = document.createElement('li')
    row.className = 'upload-item'

    var name = document.createElement('span')
    name.className = 'upload-name'
    name.textContent = file.name

    var state = document.createElement('span')
    state.className = 'upload-state'
    state.textContent = '等待上传'

    var bar = document.createElement('div')
    bar.className = 'upload-bar'
    var fill = document.createElement('div')
    fill.className = 'upload-fill'
    bar.appendChild(fill)

    row.appendChild(name)
    row.appendChild(state)
    row.appendChild(bar)
    listNode.appendChild(row)
    listNode.hidden = false
    return { state: state, fill: fill }
  }

  /** 上传单个文件；任何失败都只影响该行状态，不中断后续文件。 */
  function uploadOne(file, row) {
    return new Promise(function (resolve) {
      var request = new XMLHttpRequest()
      request.open('POST', '/upload')
      request.setRequestHeader('X-File-Name', encodeURIComponent(file.name))

      request.upload.onprogress = function (event) {
        if (!event.lengthComputable) return
        row.fill.style.width = Math.round((event.loaded / event.total) * 100) + '%'
      }

      request.onload = function () {
        var payload = null
        try {
          payload = JSON.parse(request.responseText)
        } catch (error) {
          payload = null
        }
        if (request.status === 404) {
          row.state.textContent = '会话已结束'
        } else if (payload && payload.code === 0) {
          row.fill.style.width = '100%'
          row.state.textContent = '已送达，等待电脑端确认'
        } else {
          row.state.textContent = (payload && payload.message) || '上传失败'
        }
        resolve()
      }

      request.onerror = function () {
        row.state.textContent = '网络中断，上传失败'
        resolve()
      }

      request.send(file)
    })
  }

  function uploadSequentially(files, index) {
    if (index >= files.length) {
      uploading = false
      refreshSession()
      return
    }
    var row = createRow(files[index])
    uploadOne(files[index], row).then(function () {
      uploadSequentially(files, index + 1)
    })
  }

  if (inputNode) {
    inputNode.addEventListener('change', function () {
      if (uploading) return
      var files = Array.prototype.slice.call(inputNode.files || [])
      inputNode.value = ''
      if (!files.length) return
      uploading = true
      uploadSequentially(files, 0)
    })
  }

  refreshSession()
  refreshFiles()
  window.setInterval(function () {
    refreshSession()
    refreshFiles()
  }, 20000)
})()
