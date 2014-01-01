(function($, window, document) {

    function wrapLines(text) {
        return text.replace(/\n*$/, '')  // strip
                   .replace(/^(.*)$/mg, '<span class="line">$1</span>');
    }

    function tail(log, url) {
        var s = new WebSocket(url);

        s.onopen = function() {
            console.debug('connected');
        };

        s.onmessage = function(message) {
            var data = $.parseJSON(message.data)
            if (data.type == 'message') {
                $('body').scrollTop(log[0].scrollHeight + 30);
                if (data.content != '') {
                    log[0].innerHTML += wrapLines(data.content) + '\n';
                }
            } else if (data.type == 'status' && data.content == 'finished') {
                location.reload(true);
            }
        };
        
        s.onerror = function(e) {
            console.error(e);
        };

        s.onclose = function(e) {
            console.debug('closed');
        };
    }

    $(function() {
        $('.job-log').each(function() {
            var $this = $(this);

            $this.html(function(_, oldText) {
                if (oldText != '') {
                    return wrapLines(oldText);
                }
            });
            
            var tailerUrl = $this.data('tailer-url');
            if (tailerUrl !== undefined) {
                tail($this, tailerUrl);
            }
        });
    });

}(window.jQuery, window, document));
