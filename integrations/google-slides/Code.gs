/**
 * Competitor watch -> Google Slides.
 *
 * Saves each Monday's deck (.pptx) as a Google Slides file, and answers with its link. The
 * daily GitHub job calls it right after the deck is built.
 *
 * It runs in the Google account of whoever deploys it, with the narrowest Drive permission
 * Google has ("drive.file"): it can see and change only the files it created itself. It
 * creates one folder, "Competitor watch decks", and saves the decks there. Nothing else in
 * that Drive is visible to it, or to anyone who opens a deck's link.
 *
 * Setup (once, about 5 minutes):
 *   1. script.new. Project Settings (gear) -> tick "Show appsscript.json manifest file in
 *      editor". Paste appsscript.json from this folder over it (it turns on the Drive service
 *      and asks only for the "drive.file" permission).
 *   2. Paste this file over Code.gs and set TOKEN below: any long random string. The same
 *      value goes into the GitHub secret GSLIDES_TOKEN.
 *   3. Deploy -> New deployment -> Web app. Execute as: Me. Who has access: Anyone. Deploy and
 *      allow access. Copy the Web app URL into the GitHub secret GSLIDES_HOOK_URL.
 * "Anyone" can reach the URL, but only a request with the token saves a file, and the URL
 * itself stays in GitHub's secrets.
 */

// Any long random string; the same value goes into the GitHub secret GSLIDES_TOKEN.
const TOKEN = 'PASTE_THE_SAME_TOKEN_AS_THE_GITHUB_SECRET';
const FOLDER_NAME = 'Competitor watch decks';
const SLIDES = 'application/vnd.google-apps.presentation';
const PPTX = 'application/vnd.openxmlformats-officedocument.presentationml.presentation';

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (!body || body.token !== TOKEN) return reply({ ok: false, error: 'wrong token' });
    const name = String(body.name || 'Competitor deck');
    const folder = folderId();

    // A re-run of the same week replaces its copy (the old one goes to the trash).
    const earlier = Drive.Files.list({
      q: "name = '" + name.replace(/'/g, "\\'") + "' and '" + folder + "' in parents and trashed = false",
      fields: 'files(id)'
    }).files || [];
    earlier.forEach(function (f) { Drive.Files.update({ trashed: true }, f.id); });

    // Creating a Google Slides file from a .pptx converts it.
    const blob = Utilities.newBlob(Utilities.base64Decode(body.pptx), PPTX, name + '.pptx');
    const id = Drive.Files.create({ name: name, mimeType: SLIDES, parents: [folder] }, blob).id;

    // Anyone with the link can view this one file (the link goes into Slack and the app).
    try {
      Drive.Permissions.create({ role: 'reader', type: 'anyone' }, id);
    } catch (err) {
      // Some Google Workspace domains don't allow link sharing; the copy is still saved.
    }
    return reply({ ok: true, id: id, url: 'https://docs.google.com/presentation/d/' + id + '/edit' });
  } catch (err) {
    return reply({ ok: false, error: String((err && err.message) || err) });
  }
}

/** The folder this script created on its first run. With "drive.file" it can only find
 *  folders and files it created itself, so this never picks up one of yours. */
function folderId() {
  const found = Drive.Files.list({
    q: "name = '" + FOLDER_NAME + "' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
    fields: 'files(id)'
  }).files || [];
  if (found.length) return found[0].id;
  return Drive.Files.create({ name: FOLDER_NAME, mimeType: 'application/vnd.google-apps.folder' }).id;
}

/** Open the Web app URL in a browser to check it's deployed. */
function doGet() {
  return reply({ ok: true, service: 'competitor-watch-slides' });
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
