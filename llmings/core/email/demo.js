export default {
  // Initial vault is populated in setup() so avatar URLs can be resolved
  // through ctx.assetUrl() (works in dev and offline bundle alike).
  setup(ctx) {
    const emails = [
      { id: 1, from: 'Alex Chen',  subject: 'PR Review: Session refactor', unread: true,  avatar: ctx.assetUrl('face-alex.jpg') },
      { id: 2, from: 'Lisa Park',  subject: 'Q2 roadmap draft attached',   unread: true,  avatar: ctx.assetUrl('face-lisa.jpg') },
      { id: 3, from: 'Sarah Kim',  subject: 'Q2 OKR draft for review',     unread: false, avatar: ctx.assetUrl('face-sarah.jpg') },
    ];
    ctx.vault.set('state', { emails, unreadCount: emails.filter(e => e.unread).length });
  },

  simulate(ctx) {
    ctx.interval(() => {
      const state = ctx.vault.get('state');
      const emails = state.emails.map(e => ({ ...e }));

      // Occasionally toggle unread state on a random email
      const idx = Math.floor(Math.random() * emails.length);
      emails[idx].unread = !emails[idx].unread;

      const unreadCount = emails.filter(e => e.unread).length;

      ctx.vault.set('state', { emails, unreadCount });
    }, 8000);
  }
}
