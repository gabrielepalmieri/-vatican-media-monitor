/* Morning PDF download; independent from the current-view PDF export. */
function digestEdition(data, now = Date.now()) {
  return (data?.editions || []).filter(e => e.pdf_url && /^rassegne\/rassegna-\d{4}-\d{2}-\d{2}\.pdf$/.test(e.pdf_url) && Number.isFinite(Date.parse(e.available_at)) && Date.parse(e.available_at) <= now)
    .sort((a,b) => b.date.localeCompare(a.date))[0] || null;
}

function updateMorningDigestButton() {
  const button = document.getElementById('downloadMorningDigest');
  if (!button) return;
  const edition = digestEdition(S.digest);
  button.disabled = Boolean(S.digestDownloading) || !edition;
  button.textContent = S.digestDownloading ? 'Download della rassegna…' : 'Scarica rassegna del mattino' + (edition ? ' · ' + edition.date.slice(8,10) + '/' + edition.date.slice(5,7) : '');
  button.title = edition ? 'PDF del '+edition.date+' · Attualità, Internazionale, Vaticano, Chiesa, Società, Cultura e idee' : 'La rassegna del mattino sarà disponibile dalle 7:00, ora italiana';
}

function loadMorningDigest() {
  if (S.digestPromise) return S.digestPromise;
  S.digestPromise = (async () => {
  S.digestLoading = true;
  try {
    const response = await fetch('digest.json?' + Date.now(), {cache:'no-store'});
    if (!response.ok) throw Error('Rassegna non disponibile');
    S.digest = await response.json();
    S.digestError = false;
  } catch (error) {
    S.digestError = true;
  } finally {
    S.digestLoading = false;
    S.digestPromise = null;
    updateMorningDigestButton();
  }
  })();
  return S.digestPromise;
}

async function downloadMorningDigest() {
  if (S.digestDownloading) return;
  S.digestDownloading = true;
  const status = document.getElementById('morningDigestStatus');
  if (status) status.textContent = '';
  updateMorningDigestButton();
  try {
    await loadMorningDigest();
    const edition = digestEdition(S.digest);
    if (!edition) throw Error('Il PDF del mattino non è ancora disponibile. Riprova tra poco.');
    const response = await fetch(edition.pdf_url, {cache:'no-store'});
    if (!response.ok) throw Error('Non è stato possibile scaricare il PDF. Riprova tra poco.');
    const blob = await response.blob();
    if (await blob.slice(0,5).text() !== '%PDF-') throw Error('Il PDF non è disponibile. Riprova tra poco.');
    const anchor = document.createElement('a');
    anchor.href = URL.createObjectURL(blob);
    anchor.download = 'Rassegna-del-mattino-'+edition.date+'.pdf';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(()=>URL.revokeObjectURL(anchor.href),60000);
    if (status) status.textContent = 'Rassegna del '+edition.date.slice(8,10)+'/'+edition.date.slice(5,7)+' pronta in PDF.';
  } catch (error) {
    if (status) status.textContent = error.message;
  } finally {
    S.digestDownloading = false;
    updateMorningDigestButton();
  }
}

if (typeof module !== 'undefined') module.exports = {digestEdition};
