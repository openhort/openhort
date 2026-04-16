export default {
  vault: {
    'state': {
      count: 12,
      clip1: 'const handler = async (req, ...',
      clip2: 'github.com/openhort/openhort/pull/42',
      clip3: 'Refactor the session manager to us...',
      clip1_type: 'code',
      clip2_type: 'url',
      clip3_type: 'text'
    }
  },

  simulate(ctx) {
    let count = 12;
    let clip1 = 'const handler = async (req, ...';
    let clip1_type = 'code';
    let clip2 = 'github.com/openhort/openhort/pull/42';
    let clip2_type = 'url';
    let clip3 = 'Refactor the session manager to us...';
    let clip3_type = 'text';

    const codeSnippets = [
      'const handler = async (req, ...',
      'function processEvent(data) {',
      'await fetch("/api/llmings", {',
      'export class SessionManager {',
      'if (ws.readyState === WebSocket...',
    ];
    const urls = [
      'github.com/openhort/openhort/pull/42',
      'docs.python.org/3/library/asyncio',
      'stackoverflow.com/questions/12345',
      'developer.mozilla.org/en-US/docs',
    ];
    const texts = [
      'Refactor the session manager to us...',
      'The quick brown fox jumps over th...',
      'Meeting notes: discussed the new...',
      'TODO: update the deployment scrip...',
    ];
    const types = ['code', 'url', 'text'];

    ctx.interval(() => {
      if (Math.random() < 0.3) {
        count = Math.min(99, count + 1);
        const newType = types[Math.floor(Math.random() * types.length)];
        const pool = newType === 'code' ? codeSnippets : newType === 'url' ? urls : texts;
        const newText = pool[Math.floor(Math.random() * pool.length)];

        // Shift entries down
        clip3 = clip2;
        clip3_type = clip2_type;
        clip2 = clip1;
        clip2_type = clip1_type;
        clip1 = newText;
        clip1_type = newType;

        ctx.vault.set('state', {
          count,
          clip1, clip1_type,
          clip2, clip2_type,
          clip3, clip3_type,
        });
      }
    }, 3000);
  }
}
