var webSocketBridge;

$.ajaxSetup({
  beforeSend: function(xhr, settings) {
    if (settings.type == 'POST' && !this.crossDomain) {
      csrftoken = document.cookie.replace(/^(.*;)?\s*csrftoken=(\w+?)(;.*)?/, '$2');
      xhr.setRequestHeader("X-CSRFToken", csrftoken);
    }
  }
})



function receiveMessage(msg) {
  var type = String(msg['type']);
  var fid = Number(msg['id']);

  if (type == 'input') {
    if (msg['val'] === null) {
      $('[data-id=' + fid + '].dw-input')
        .prop('disabled', Boolean(msg['disabled']));
    } else {
      $('[data-id=' + fid + '].dw-input')
        .val(String(msg['val']))
        .prop('disabled', Boolean(msg['disabled']));
    }
  }

  if (type == 'display') {
    $('span[data-id=' + fid + '].dw-input')
      .html(msg['val'] ? msg['val'] : "");
  }
}



$(document).ready(function() {
  webSocketBridge = new channels.WebSocketBridge();
  webSocketBridge.connect('/ws/django-wiki-inputs?path=' + location.pathname);
  webSocketBridge.listen(receiveMessage)
})



function sendUpdate(e) {
    var fid = e.attr('data-id');
    var type = e.attr('type');

    if (type == 'file') {
        var n = e.context.files.length;
        var data = [];

        for (var i = 0; i < n; i++) {
            var reader = new FileReader();
            //reader._file = ev.target.files[i];
            reader._file = e.context.files[i];

            reader.onload = function(ev2) {
                if (ev2.target.result == 'data:') {
                    /* empty file */
                    var content = "";
                    var type = "application/x-empty";
                } else {
                    var r = ev2.target.result.split(';base64,');
                    var type = r[0].slice(5);
                    var content = r[r.length - 1];
                }

                data.push({name: ev2.target._file.name,
                          size: ev2.target._file.size,
                          type: type,
                          content: content});

                if (data.length == n) {
                    webSocketBridge.send({id: fid, val: data});
                }
            }
            reader.readAsDataURL(reader._file);
        }
    } else {
        webSocketBridge.send({id: fid, val: e.val()});
    }

    e.removeClass('dw-need-update');
}


$('input[data-id].dw-input, textarea[data-id].dw-input').on('input', function() {
    var e = $(this);

    if (e.data('send_update')) {
        clearTimeout(e.data('send_update'));
    }

    e.addClass('dw-need-update');
    e.data('send_update', setTimeout(function() {
      e.removeData('send_update');
      sendUpdate(e);
    }, 10000));

    e.change(function(ev) {
        if (e.data('send_update')) {
            clearTimeout(e.data('send_update'));
            e.removeData('send_update');
        }

        sendUpdate(e);
    });
});
