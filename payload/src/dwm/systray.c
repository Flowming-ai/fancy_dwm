/* XEmbed system tray, adapted from suckless's systray patch (2023-09-22).
 * Reference: https://dwm.suckless.org/patches/systray/
 * Keep its windows outside Client lists so swallowing, tags and scratchpads
 * cannot accidentally manage an icon. No StatusNotifier bridge is provided.
 */
#define XEMBED_EMBEDDED_NOTIFY 0
#define XEMBED_WINDOW_ACTIVATE 1
#define XEMBED_WINDOW_DEACTIVATE 2
#define XEMBED_MAPPED (1UL << 0)

static void
traymessage(Window w, long opcode, long detail, long data1, long data2)
{
	XEvent e = {0};
	e.xclient.type = ClientMessage;
	e.xclient.window = w;
	e.xclient.message_type = trayatom[TrayXembed];
	e.xclient.format = 32;
	e.xclient.data.l[0] = CurrentTime;
	e.xclient.data.l[1] = opcode;
	e.xclient.data.l[2] = detail;
	e.xclient.data.l[3] = data1;
	e.xclient.data.l[4] = data2;
	XSendEvent(dpy, w, False, NoEventMask, &e);
}

Monitor *
systraymon(void)
{
	Monitor *m, *right = mons;
	for (m = mons; m; m = m->next)
		if (!right || m->mx + m->mw > right->mx + right->mw
		|| (m->mx + m->mw == right->mx + right->mw && m->mx > right->mx))
			right = m;
	return right;
}

TrayIcon *
wintosystrayicon(Window w)
{
	TrayIcon *i;
	for (i = systrayicons; i; i = i->next)
		if (i->win == w)
			return i;
	return NULL;
}

unsigned int
systraywidth(Monitor *m)
{
	unsigned int width = 0;
	TrayIcon *i;
	if (!systraywin || !m || m != systraymon())
		return 0;
	for (i = systrayicons; i; i = i->next)
		if (i->mapped)
			width += i->w + systrayspacing;
	if (width)
		width += systrayspacing;
	/* Even an excessive number of icons must not produce a negative bar. */
	return MIN(width, (unsigned int)MAX(0, m->ww - 1));
}

void
resizebarwin(Monitor *m)
{
	if (m->barwin)
		XMoveResizeWindow(dpy, m->barwin, m->wx, m->by,
			MAX(1, m->ww - systraywidth(m)), bh);
}

void
updatesystrayicongeom(TrayIcon *i, int w, int h)
{
	i->h = bh;
	/* Limit unusual aspect ratios, and never divide by a zero client size. */
	i->w = MAX(1, MIN(2 * bh, (int)((double)MAX(1, w) * bh / MAX(1, h))));
}

void
updatesystrayiconstate(TrayIcon *i)
{
	Atom type;
	int format, mapped = i->mapped;
	unsigned long count, extra;
	unsigned char *data = NULL;
	if (XGetWindowProperty(dpy, i->win, trayatom[TrayXembedInfo], 0, 2,
		False, trayatom[TrayXembedInfo], &type, &format, &count, &extra,
		&data) == Success && data && type == trayatom[TrayXembedInfo]
		&& format == 32 && count == 2)
		mapped = !!(((unsigned long *)data)[1] & XEMBED_MAPPED);
	if (data)
		XFree(data);
	if (mapped != i->mapped) {
		i->mapped = mapped;
		if (wintosystrayicon(i->win))
			traymessage(i->win, mapped ? XEMBED_WINDOW_ACTIVATE
				: XEMBED_WINDOW_DEACTIVATE, 0, 0, 0);
	}
}

void
updatesystray(void)
{
	Monitor *m, *host = systraymon();
	TrayIcon *i;
	unsigned int width = systraywidth(host);
	int x = systrayspacing;
	XWindowChanges wc;
	if (systraywin && host) {
		XSetWindowBackground(dpy, systraywin, scheme[SchemeNorm][ColBg].pixel);
		for (i = systrayicons; i; i = i->next) {
			if (!i->mapped) {
				XUnmapWindow(dpy, i->win);
				continue;
			}
			XMoveResizeWindow(dpy, i->win, x, (bh - i->h) / 2, i->w, i->h);
			XMapWindow(dpy, i->win);
			x += i->w + systrayspacing;
		}
		XMoveResizeWindow(dpy, systraywin, host->wx + host->ww - width,
			host->by, MAX(1, width), bh);
		if (host->showbar && width) {
			XMapWindow(dpy, systraywin);
			/* Keep the same layer as the bar, below raised fullscreen clients. */
			wc.sibling = host->barwin;
			wc.stack_mode = Above;
			XConfigureWindow(dpy, systraywin, CWSibling|CWStackMode, &wc);
			XClearWindow(dpy, systraywin);
		} else
			XUnmapWindow(dpy, systraywin);
	}
	for (m = mons; m; m = m->next)
		resizebarwin(m);
	drawbars();
}

void
setupsystray(void)
{
	char selection[64];
	unsigned long orientation = 0, visual, iconheight = bh;
	XSetWindowAttributes wa = {
		.override_redirect = True,
		.event_mask = SubstructureNotifyMask|SubstructureRedirectMask|PropertyChangeMask,
		.background_pixel = scheme[SchemeNorm][ColBg].pixel
	};
	XClassHint ch = { "systray", "dwm" };
	XEvent event = {0};
	Time timestamp;
	if (!showsystray)
		return;
	snprintf(selection, sizeof selection, "_NET_SYSTEM_TRAY_S%d", screen);
	trayatom[TraySelection] = XInternAtom(dpy, selection, False);
	trayatom[TrayOpcode] = XInternAtom(dpy, "_NET_SYSTEM_TRAY_OPCODE", False);
	trayatom[TrayOrientation] = XInternAtom(dpy, "_NET_SYSTEM_TRAY_ORIENTATION", False);
	trayatom[TrayVisual] = XInternAtom(dpy, "_NET_SYSTEM_TRAY_VISUAL", False);
	trayatom[TrayIconSize] = XInternAtom(dpy, "_NET_SYSTEM_TRAY_ICON_SIZE", False);
	trayatom[TrayManager] = XInternAtom(dpy, "MANAGER", False);
	trayatom[TrayXembed] = XInternAtom(dpy, "_XEMBED", False);
	trayatom[TrayXembedInfo] = XInternAtom(dpy, "_XEMBED_INFO", False);
	if (XGetSelectionOwner(dpy, trayatom[TraySelection]) != None) {
		fputs("dwm: another system tray owns the selection; built-in tray disabled\n", stderr);
		return;
	}
	systraywin = XCreateWindow(dpy, root, 0, 0, 1, bh, 0,
		DefaultDepth(dpy, screen), InputOutput, DefaultVisual(dpy, screen),
		CWOverrideRedirect|CWBackPixel|CWEventMask, &wa);
	XSetClassHint(dpy, systraywin, &ch);
	XStoreName(dpy, systraywin, "dwm-systray");
	XChangeProperty(dpy, systraywin, trayatom[TrayOrientation], XA_CARDINAL,
		32, PropModeReplace, (unsigned char *)&orientation, 1);
	visual = XVisualIDFromVisual(DefaultVisual(dpy, screen));
	XChangeProperty(dpy, systraywin, trayatom[TrayVisual], XA_VISUALID,
		32, PropModeReplace, (unsigned char *)&visual, 1);
	XChangeProperty(dpy, systraywin, trayatom[TrayIconSize], XA_CARDINAL,
		32, PropModeReplace, (unsigned char *)&iconheight, 1);
	/* Get a real server timestamp for selection ownership and MANAGER. */
	XWindowEvent(dpy, systraywin, PropertyChangeMask, &event);
	timestamp = event.xproperty.time;
	XGrabServer(dpy);
	if (XGetSelectionOwner(dpy, trayatom[TraySelection]) == None)
		XSetSelectionOwner(dpy, trayatom[TraySelection], systraywin, timestamp);
	if (XGetSelectionOwner(dpy, trayatom[TraySelection]) != systraywin) {
		XDestroyWindow(dpy, systraywin);
		systraywin = None;
		XUngrabServer(dpy);
		fputs("dwm: could not acquire system tray selection; leaving existing owner alone\n", stderr);
		return;
	}
	XUngrabServer(dpy);
	memset(&event, 0, sizeof event);
	event.xclient.type = ClientMessage;
	event.xclient.window = root;
	event.xclient.message_type = trayatom[TrayManager];
	event.xclient.format = 32;
	event.xclient.data.l[0] = timestamp;
	event.xclient.data.l[1] = trayatom[TraySelection];
	event.xclient.data.l[2] = systraywin;
	XSendEvent(dpy, root, False, StructureNotifyMask, &event);
	updatesystray();
}

void
docksystrayicon(Window w)
{
	XWindowAttributes wa;
	TrayIcon *i, **tail;
	Monitor *m;
	if (!systraywin || !w || w == root || w == systraywin || w == wmcheckwin
	|| wintosystrayicon(w) || wintoclient(w))
		return;
	for (m = mons; m; m = m->next)
		if (w == m->barwin)
			return;
	if (!XGetWindowAttributes(dpy, w, &wa) || wa.class != InputOutput)
		return;
	i = ecalloc(1, sizeof *i);
	i->win = w;
	i->oldbw = wa.border_width;
	i->mapped = 1; /* tolerate older clients without _XEMBED_INFO */
	updatesystrayicongeom(i, wa.width, wa.height);
	updatesystrayiconstate(i);
	for (tail = &systrayicons; *tail; tail = &(*tail)->next);
	*tail = i;
	XAddToSaveSet(dpy, w);
	XSelectInput(dpy, w, StructureNotifyMask|PropertyChangeMask|ResizeRedirectMask);
	XSetWindowBorderWidth(dpy, w, 0);
	XReparentWindow(dpy, w, systraywin, 0, 0);
	traymessage(w, XEMBED_EMBEDDED_NOTIFY, 0, systraywin, 0);
	if (i->mapped)
		traymessage(w, XEMBED_WINDOW_ACTIVATE, 0, 0, 0);
	updatesystray();
}

void
removesystrayicon(TrayIcon *icon, int destroyed)
{
	TrayIcon **p;
	for (p = &systrayicons; *p && *p != icon; p = &(*p)->next);
	if (!*p)
		return;
	*p = icon->next;
	if (!destroyed) {
		XSelectInput(dpy, icon->win, NoEventMask);
		XRemoveFromSaveSet(dpy, icon->win);
		XSetWindowBorderWidth(dpy, icon->win, icon->oldbw);
	}
	free(icon);
}

void
cleanupsystray(void)
{
	TrayIcon *i;
	if (!systraywin)
		return;
	/* Preserve foreign icon windows across WM exit/restart. Their toolkits
	 * watch the selection and will dock again when MANAGER is announced. */
	while ((i = systrayicons)) {
		traymessage(i->win, XEMBED_WINDOW_DEACTIVATE, 0, 0, 0);
		XUnmapWindow(dpy, i->win);
		XReparentWindow(dpy, i->win, root, 0, 0);
		XDeleteProperty(dpy, i->win, wmatom[WMState]);
		removesystrayicon(i, 0);
	}
	if (XGetSelectionOwner(dpy, trayatom[TraySelection]) == systraywin)
		XSetSelectionOwner(dpy, trayatom[TraySelection], None, CurrentTime);
	XDestroyWindow(dpy, systraywin);
	systraywin = None;
	XSync(dpy, False);
}

void
selectionclear(XEvent *e)
{
	if (systraywin && e->xselectionclear.selection == trayatom[TraySelection]
	&& e->xselectionclear.window == systraywin) {
		fputs("dwm: system tray selection lost; releasing icons\n", stderr);
		cleanupsystray();
		updatesystray();
	}
}

void
resizerequest(XEvent *e)
{
	TrayIcon *i = wintosystrayicon(e->xresizerequest.window);
	if (i) {
		updatesystrayicongeom(i, e->xresizerequest.width, e->xresizerequest.height);
		updatesystray();
	}
}

void
reparentnotify(XEvent *e)
{
	TrayIcon *i = wintosystrayicon(e->xreparent.window);
	if (i && e->xreparent.parent != systraywin) {
		removesystrayicon(i, 0);
		updatesystray();
	}
}
