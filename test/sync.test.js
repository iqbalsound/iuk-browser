const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { createServer } = require('../server/server.js');
const { device } = require('./helpers.js');

test('two devices: setup, sync bookmarks + passwords, deletes propagate, wrong key rejected', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vfs-'));
  const srv = createServer({ dataDir: dir }); await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const server = 'http://127.0.0.1:' + srv.address().port;
  try {
    const A = device(), B = device();
    // Device A has a bookmark inside a folder and a login
    const f = await A.m.browser.bookmarks.create({ parentId: 'toolbar_____', title: 'News' });
    await A.bm(f.id, 'HN', 'https://news.ycombinator.com/');
    await A.bm('unfiled_____', 'Docs', 'https://example.org/docs');
    await A.core.setup({ username: 'me@x.com', secret: 'my-secret-connect-key', server });
    await A.core.saveLogin({ host: 'https://www.github.com/login', username: 'iqbal', password: 'pw-one' });
    await A.core.syncNow();

    // Device B joins with the same credentials and already has its own bookmark
    await B.bm('toolbar_____', 'Mine', 'https://b-only.example/');
    await B.core.setup({ username: 'ME@x.com', secret: 'my-secret-connect-key', server });
    assert.deepEqual(B.urls(), ['https://b-only.example/', 'https://example.org/docs', 'https://news.ycombinator.com/']);
    const hn = Object.values(B.m.nodes).find((x) => x.url === 'https://news.ycombinator.com/');
    assert.equal(B.m.nodes[hn.parentId].title, 'News'); // folder structure recreated
    assert.equal(B.core.getSecret('github.com|iqbal'), 'pw-one');

    // B changes the password and deletes a bookmark; A picks both up
    await new Promise((r) => setTimeout(r, 5));
    await B.core.saveLogin({ host: 'github.com', username: 'iqbal', password: 'pw-two' });
    await B.m.browser.bookmarks.remove(Object.values(B.m.nodes).find((x) => x.url === 'https://example.org/docs').id);
    await B.core.syncNow(); await A.core.syncNow();
    assert.equal(A.core.getSecret('github.com|iqbal'), 'pw-two');
    assert.ok(!A.urls().includes('https://example.org/docs')); assert.ok(A.urls().includes('https://b-only.example/'));
    assert.deepEqual(A.urls(), B.urls());

    // lock/unlock round trip; wrong key is refused
    A.core.lock(); assert.throws(() => A.core.listLogins(), /locked/);
    await assert.rejects(() => A.core.unlock({ username: 'me@x.com', secret: 'not-the-right-key!!' }), /Wrong/);
    await A.core.unlock({ username: 'me@x.com', secret: 'my-secret-connect-key' });
    assert.equal(A.core.listLogins('login.github.com').length, 1);
    assert.equal(A.core.listLogins('evil-github.com').length, 0);

    // a device with a different key is simply a different account: it sees none of the first one's data
    const C = device();
    await C.core.setup({ username: 'me@x.com', secret: 'totally-other-key-123', server });
    assert.equal(C.core.listLogins().length, 0); assert.deepEqual(C.urls(), []);
    assert.equal(fs.readdirSync(dir).filter((x) => x.endsWith('.blob')).length, 2);
    // data on the server is ciphertext only
    const blob = fs.readdirSync(dir).map((x) => fs.readFileSync(path.join(dir, x), 'utf8')).join('');
    assert.ok(!/pw-two|github|ycombinator/.test(blob));
  } finally { srv.closeAllConnections(); srv.close(); }
});
