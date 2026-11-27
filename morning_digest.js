/* Daily morning edition; all dates use Europe/Rome, including summer time. */
function digestEdition(data, now = Date.now()) {
  return (data?.editions || []).filter(e => Number.isFinite(Date.parse(e.available_at)) && Date.parse(e.available_at) <= now)
    .sort((a, b) => b.date.localeCompare(a.date))[0] || null;
}

async function loadMorningDigest() {
  if (S.digestLoading) return;
  S.digestLoading = true;
  try {
    const response = await fetch('digest.json?' + Date.now(), {cache: 'no-store'});
    if (!response.ok) throw Error('Rassegna non disponibile');
    S.digest = await response.json();
    S.digestError = false;
  } catch (error) {
    S.digestError = true;
  } finally {
    S.digestLoading = false;
    if (S.view === 'digest') renderMorningDigest();
  }
}

function renderMorningDigest() {
  const edition = digestEdition(S.digest);
  const dateLabel = value => new Date(value + 'T12:00:00+01:00').toLocaleDateString('it-IT', {timeZone: 'Europe/Rome', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
  const timeLabel = value => new Date(value).toLocaleString('it-IT', {timeZone: 'Europe/Rome', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  const sections = edition?.sections || ['Attualità', 'Vaticano', 'Società'].map(title => ({title, items: []}));
  S.filtered = sections.flatMap(section => section.items.map(item => ({...item, topic: section.title, section: section.title})));
  $('#viewTitle').textContent = 'Rassegna delle 7';
  $('#count').textContent = S.filtered.length + ' notizie · 3 sezioni';
  $('#moreResults').hidden = true;
  $('#digestDate').textContent = edition ? dateLabel(edition.date) : 'Edizione del mattino';
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Rome', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  const hour = Number(new Intl.DateTimeFormat('en-GB', {timeZone: 'Europe/Rome', hour: '2-digit', hourCycle: 'h23'}).format(new Date()));
  let note = edition ? 'Notizie delle 24 ore precedenti, raccolte fino al ' + timeLabel(edition.coverage_to) + '. Edizione giornaliera disponibile dalle 7:00, ora italiana.' : (S.digestLoading ? 'Caricamento della rassegna…' : 'La rassegna del mattino non è ancora disponibile.');
  if (edition && edition.date !== today) note = (hour < 7 ? 'Prossima edizione dalle 7:00. ' : 'L’edizione di oggi non è ancora disponibile. ') + 'È mostrata la rassegna del ' + dateLabel(edition.date) + '.';
  if (S.digestError) note += ' Il controllo dell’aggiornamento non è riuscito; riprova tra poco.';
  $('#digestNote').textContent = note;
  $('#stories').innerHTML = sections.map(section => `<section class="digest-section"><h2>${esc(section.title)}</h2>${section.items.length ? section.items.map(item => {
    const translate = 'https://translate.google.com/?sl=auto&tl=it&text=' + encodeURIComponent(item.title) + '&op=translate';
    return `<article class="story"><div><div class="meta"><b>${esc(item.source)}</b>${item.author ? `<span>· ${esc(item.author)}</span>` : ''}<time datetime="${esc(item.published)}">${esc(timeLabel(item.published))}</time></div><h3><a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a></h3>${item.summary ? `<p class="digest-excerpt">${esc(item.summary)}</p>` : ''}</div><div class="story-side">${item.language && item.language !== 'Italiano' ? `<a class="translate" href="${translate}" target="_blank" rel="noopener">Traduci titolo</a>` : ''}</div></article>`;
  }).join('') : '<p class="digest-empty">Nessuna notizia recente disponibile per questa sezione.</p>'}</section>`).join('');
  updatePrintMeta();
}

if (typeof module !== 'undefined') module.exports = {digestEdition};
