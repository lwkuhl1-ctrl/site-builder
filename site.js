(function () {
  var burger = document.querySelector('.burger'), menu = document.getElementById('mnav');
  if (burger && menu) burger.addEventListener('click', function () {
    var open = menu.hidden;
    menu.hidden = !open;
    burger.setAttribute('aria-expanded', String(open));
  });

  document.documentElement.classList.add('js');

  // Header tightens once the page scrolls (watches a 1px marker at the top, no scroll listener).
  var hdr = document.querySelector('.hdr');
  if (hdr && 'IntersectionObserver' in window) {
    var mark = document.createElement('div');
    mark.style.cssText = 'position:absolute;top:0;left:0;height:1px;width:1px';
    document.body.prepend(mark);
    new IntersectionObserver(function (es) { hdr.classList.toggle('scrolled', !es[0].isIntersecting); }).observe(mark);
  }

  // Sections and cards rise in as they reach the screen; siblings stagger slightly.
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (x) { if (x.isIntersecting) { x.target.classList.add('in'); io.unobserve(x.target); } });
    }, { rootMargin: '0px 0px -60px 0px' });
    if (document.body.classList.contains('anim')) {
      document.querySelectorAll('.sec .shead, .card, .steps li, .quote, .gallery figure, .about-copy, .about-media, .ba, .chips, .faq, .facts, .badges li, .cta-in')
        .forEach(function (el) {
          var i = Array.prototype.indexOf.call(el.parentNode.children, el);
          if (i > 0 && i < 8) el.style.transitionDelay = (i * 70) + 'ms';
          el.classList.add('reveal'); io.observe(el);
        });
    }
    document.querySelectorAll('.steps').forEach(function (el) { io.observe(el); });   // draws the line between steps
  }
  // Safety net: content must never stay hidden (old browsers, background tabs, odd observers).
  function showVisible() {
    document.querySelectorAll('.reveal:not(.in), .steps:not(.in)').forEach(function (el) {
      if (el.getBoundingClientRect().top < innerHeight) el.classList.add('in');
    });
  }
  requestAnimationFrame(showVisible);
  setTimeout(function () { document.querySelectorAll('.reveal, .steps').forEach(function (el) { el.classList.add('in'); }); }, 3000);

  // Before/after slider.
  document.querySelectorAll('.ba input').forEach(function (r) {
    var box = r.closest('.ba');
    r.addEventListener('input', function () { box.style.setProperty('--pos', r.value + '%'); });
  });

  var LABELS = { name: 'Name', phone: 'Phone', email: 'Email', service: 'Service', address: 'Where',
    date: 'Preferred day', time: 'Preferred time', message: 'Details' };
  var MAX_PHOTOS = 6, MAX_SIDE = 1600;

  // Phone photos are often 4-10 MB; shrink each to a ~300 KB JPEG so a batch fits the form service's limit.
  function shrink(file) {
    return new Promise(function (ok, bad) {
      var url = URL.createObjectURL(file), img = new Image();
      img.onload = function () {
        var k = Math.min(1, MAX_SIDE / Math.max(img.width, img.height)), c = document.createElement('canvas');
        c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
        c.toBlob(function (b) {
          b ? ok(new File([b], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' })) : bad(new Error('resize'));
        }, 'image/jpeg', 0.82);
      };
      img.onerror = function () { URL.revokeObjectURL(url); bad(new Error(file.name)); };
      img.src = url;
    });
  }

  document.querySelectorAll('.qform').forEach(function (form) {
    var status = form.querySelector('.fstatus'), btn = form.querySelector('button[type=submit]');
    var phone = form.querySelector('input[name=phone]'), btnText = btn.textContent;
    var day = form.querySelector('input[name=date]');
    var photoIn = form.querySelector('.photo-up input[type=file]'), thumbs = form.querySelector('.photo-thumbs');
    var photos = [];                                         // shrunk File objects, in the order picked
    if (day) { var t = new Date(); day.min = new Date(t.getTime() - t.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }
    phone.addEventListener('input', function () {
      var d = phone.value.replace(/\D/g, '');
      if (phone.value.trim().charAt(0) === '+' || d.length > 10) return;
      phone.value = d.length > 6 ? '(' + d.slice(0, 3) + ') ' + d.slice(3, 6) + '-' + d.slice(6)
        : d.length > 3 ? '(' + d.slice(0, 3) + ') ' + d.slice(3) : d.length ? '(' + d : '';
    });

    function say(msg, ok) { status.textContent = msg; status.className = 'fstatus ' + (ok ? 'ok' : 'err'); }

    function syncPhotos() {
      thumbs.innerHTML = '';
      photos.forEach(function (f, i) {
        var d = document.createElement('div'), x = document.createElement('button');
        d.style.backgroundImage = 'url(' + URL.createObjectURL(f) + ')';
        x.type = 'button'; x.textContent = '×'; x.setAttribute('aria-label', 'Remove photo ' + (i + 1));
        x.addEventListener('click', function () { photos.splice(i, 1); syncPhotos(); });
        d.appendChild(x); thumbs.appendChild(d);
      });
      // Put the shrunk photos back on the input so a normal form post sends them.
      try { var dt = new DataTransfer(); photos.forEach(function (f) { dt.items.add(f); }); photoIn.files = dt.files; } catch (_) {}
    }

    if (photoIn) photoIn.addEventListener('change', function () {
      var picked = Array.prototype.slice.call(photoIn.files).filter(function (f) { return /^image\//.test(f.type); });
      var room = MAX_PHOTOS - photos.length;
      if (picked.length > room) say('Up to ' + MAX_PHOTOS + ' photos. We kept the first ' + Math.max(room, 0) + '.', false);
      Promise.all(picked.slice(0, Math.max(room, 0)).map(function (f) { return shrink(f).catch(function () { return null; }); }))
        .then(function (done) { photos = photos.concat(done.filter(Boolean)); syncPhotos(); });
    });

    form.addEventListener('submit', function (ev) {
      if (form.website.value) { ev.preventDefault(); return; }   // honeypot
      if (!form.checkValidity()) { ev.preventDefault(); form.reportValidity(); return; }
      try { gtag('event', 'generate_lead', { form: 'quote', photos: photos.length }); } catch (_) {}
      var endpoint = form.dataset.endpoint;

      // FormSubmit: let the browser post the form (photos attached); it emails the owner, then shows /thank-you/.
      if (form.dataset.native) { btn.disabled = true; btn.textContent = 'Sending…'; return; }
      ev.preventDefault();
      var data = new FormData(form);
      data.delete('attachment');
      photos.forEach(function (f) { data.append('attachment', f); });

      if (endpoint) {
        btn.disabled = true; btn.textContent = 'Sending…';
        fetch(endpoint, { method: 'POST', body: data, headers: { Accept: 'application/json' } })
          .then(function (r) { if (!r.ok) throw new Error(r.status); form.reset(); photos = []; if (thumbs) syncPhotos();
            say("Thanks! We got your request and will get back to you shortly.", true); })
          .catch(function () { say('That didn’t send. Please call or text us instead.', false); })
          .finally(function () { btn.disabled = false; btn.textContent = btnText; });
        return;
      }
      // No form service set up: hand the request to the visitor's text or email app.
      var subject = data.get('subject').replace(' from your website', '');
      var body = subject + ' for ' + form.dataset.biz;
      Object.keys(LABELS).forEach(function (k) { if (data.get(k)) body += '\n' + LABELS[k] + ': ' + data.get(k); });
      var tel = form.dataset.tel, email = form.dataset.email;
      if (tel) location.href = 'sms:' + tel + '?&body=' + encodeURIComponent(body);
      else if (email) location.href = 'mailto:' + email + '?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
      say((tel ? 'Your text app' : 'Your email app') + ' should open with your request filled in.' +
          (photos.length ? ' Attach your photos in that message, then hit send.' : ' Just hit send.'), true);
    });
  });
})();
