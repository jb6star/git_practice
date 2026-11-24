// 책 추가/수정 화면: Google Books 검색으로 제목·저자·표지 채우기 + 미리보기
(() => {
  const $ = (id) => document.getElementById(id);
  const title = $('f-title'), author = $('f-author'), coverInput = $('f-cover');
  const img = $('preview-img'), pTitle = $('preview-title');
  const results = $('results'), q = $('q');

  const updatePreview = () => {
    pTitle.textContent = title.value || '제목';
    if (coverInput.value) { img.src = coverInput.value; img.hidden = false; }
    else { img.removeAttribute('src'); img.hidden = true; }
  };
  img.addEventListener('error', () => { img.hidden = true; });
  title.addEventListener('input', updatePreview);
  coverInput.addEventListener('change', updatePreview);

  // 상태가 '읽는 중'이면 완독일 입력 숨기기
  const dateField = $('date-field');
  const syncStatus = () => {
    const v = document.querySelector('input[name=status]:checked').value;
    dateField.hidden = v !== 'done';
  };
  document.querySelectorAll('input[name=status]').forEach(r => r.addEventListener('change', syncStatus));
  syncStatus();

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  async function search() {
    const term = q.value.trim();
    if (!term) return;
    results.innerHTML = '<p class="muted small">검색 중…</p>';
    try {
      const url = 'https://www.googleapis.com/books/v1/volumes?maxResults=12&q=' + encodeURIComponent(term);
      const res = await fetch(url);
      const data = await res.json();
      const items = (data.items || []).map(it => {
        const v = it.volumeInfo || {};
        const thumb = (v.imageLinks && (v.imageLinks.thumbnail || v.imageLinks.smallThumbnail) || '')
          .replace(/^http:/, 'https:').replace('&edge=curl', '');
        return { title: v.title || '', author: (v.authors || []).join(', '), thumb };
      });
      if (!items.length) { results.innerHTML = '<p class="muted small">검색 결과가 없어요. 직접 입력해 주세요.</p>'; return; }
      results.innerHTML = items.map((b, i) => `
        <button type="button" class="result" data-i="${i}">
          ${b.thumb ? `<img src="${escapeHtml(b.thumb)}" alt="">` : '<span class="noimg">📕</span>'}
          <span><strong>${escapeHtml(b.title)}</strong><br><span class="muted small">${escapeHtml(b.author)}</span></span>
        </button>`).join('');
      results.querySelectorAll('.result').forEach(btn => btn.addEventListener('click', () => {
        const b = items[+btn.dataset.i];
        title.value = b.title; author.value = b.author; coverInput.value = b.thumb;
        updatePreview();
        results.innerHTML = '';
        title.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }));
    } catch (e) {
      results.innerHTML = '<p class="muted small">검색에 실패했어요. 직접 입력해 주세요.</p>';
    }
  }
  $('search-btn').addEventListener('click', search);
  q.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); search(); } });
})();
