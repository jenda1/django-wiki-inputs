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
  var fid = Number(msg['id']);
  var e = $('span[data-id=' + fid + '].dw-input');

  e.html(msg['html']);
}



$(document).ready(function() {
  webSocketBridge = new channels.WebSocketBridge();
  webSocketBridge.connect('/ws/django-wiki-inputs?path=' + location.pathname);
  webSocketBridge.listen(receiveMessage)
})

$('input[data-id].dw-input').on('input', function() {
    var e = $(this);
    var fid = e.attr('data-id');

    e.addClass('dw-need-update');

    if (e.data('send_update')) {
      clearTimeout(e.data('send_update'));
    }

    e.data('send_update', setTimeout(function() {
      e.removeData('send_update');
      webSocketBridge.send({id: fid, val: e.val()});
      e.removeClass('dw-need-update');
    }, 10000));

    e.change(function() {
      if (e.data('send_update')) {
        clearTimeout(e.data('send_update'));
        e.removeData('send_update');
        webSocketBridge.send({id: fid, val: e.val()});
        e.removeClass('dw-need-update');
      }
    });
  });

