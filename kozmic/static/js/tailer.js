(function($, window, document) {

    function wrapLines(text, lineNumber) {
        var i = lineNumber;
        var result = text.replace(/\n*$/, '').replace(/^(.*)$/mg, function(match) {
            return ('<span class="line" id="' + i + '"><a href="#' + (i++) + '" class="number">' +
                i + '</a>' + match + '</span>');
        });
        return {lineNumber: i, result: result};
    }

    function tail(log, url, lineNumber) {
        var s = new WebSocket(url);

        s.onopen = function() {
            console.debug('connected');
        };

        s.onmessage = function(message) {
            var data = $.parseJSON(message.data)
            if (data.type == 'message') {
                $('body').scrollTop(log[0].scrollHeight + 30);
                if (data.content != '') {
                    var r = wrapLines(data.content, lineNumber);
                    lineNumber = r.lineNumber;
                    log[0].innerHTML += r.result + '\n';
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

            var lineNumber = 0;
            $this.html(function(_, oldText) {
                if (oldText != '') {
                    var r = wrapLines(oldText, lineNumber);
                    lineNumber = r.lineNumber;
                    return r.result;
                }
            });
            
            var tailerUrl = $this.data('tailer-url');
            if (tailerUrl !== undefined) {
                tail($this, tailerUrl, lineNumber);
            }
        });
    });

}(window.jQuery, window, document));
