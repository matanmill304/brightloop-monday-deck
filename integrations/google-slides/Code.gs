/**
 * Competitor watch -> Google Slides.
 *
 * Saves each Monday's deck (.pptx) as a native Google Slides file in one Drive folder, and
 * answers with its link. The daily GitHub job calls it right after the deck is built.
 *
 * Setup (once, about 5 minutes):
 *   1. In Drive, create a folder (e.g. "Competitor watch decks") and copy its ID from the URL:
 *      drive.google.com/drive/folders/<THIS PART>
 *   2. Paste the folder ID and a token below. The token is any long random string; the same
 *      value goes into the GitHub secret GSLIDES_TOKEN.
 *   3. Services (+) -> Drive API -> Add.
 *   4. Deploy -> New deployment -> Web app. Execute as: Me. Who has access: Anyone. Deploy and
 *      allow access. Copy the Web app URL into the GitHub secret GSLIDES_HOOK_URL.
 *
 * "Anyone" can reach the URL, but only a request with the token saves a file.
 */

const FOLDER_ID = 'PASTE_THE_FOLDER_ID';
const TOKEN = 'PASTE_THE_SAME_TOKEN_AS_THE_GITHUB_SECRET';

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (!body || body.token !== TOKEN) return reply({ ok: false, error: 'wrong token' });
    const name = String(body.name || 'Competitor deck');
    const blob = Utilities.newBlob(
      Utilities.base64Decode(body.pptx),
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      name + '.pptx'
    );
    // A re-run of the same week replaces its copy (the old one goes to the trash).
    const folder = DriveApp.getFolderById(FOLDER_ID);
    const earlier = folder.getFilesByName(name);
    while (earlier.hasNext()) earlier.next().setTrashed(true);

    let id;
    if (Drive.Files.create) {
      // Drive API v3: creating a Google Slides file from a .pptx converts it.
      id = Drive.Files.create({ name: name, mimeType: MimeType.GOOGLE_SLIDES, parents: [FOLDER_ID] }, blob).id;
    } else {
      // Drive API v2
      id = Drive.Files.insert({ title: name, mimeType: MimeType.GOOGLE_SLIDES, parents: [{ id: FOLDER_ID }] }, blob, { convert: true }).id;
    }
    try {
      // Anyone with the link can view: the link goes into Slack and the app.
      DriveApp.getFileById(id).setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    } catch (err) {
      // Some Google Workspace domains don't allow link sharing; the copy is still saved.
    }
    return reply({ ok: true, id: id, url: 'https://docs.google.com/presentation/d/' + id + '/edit' });
  } catch (err) {
    return reply({ ok: false, error: String((err && err.message) || err) });
  }
}

/** Open the Web app URL in a browser to check it's deployed. */
function doGet() {
  return reply({ ok: true, service: 'competitor-watch-slides' });
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
