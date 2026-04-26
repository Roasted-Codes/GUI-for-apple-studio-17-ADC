PACKAGE = pi-adc-control
VERSION = 2.0
DEB = $(PACKAGE)_$(VERSION)_all.deb
BUILDDIR = build/$(PACKAGE)_$(VERSION)_all

.PHONY: deb clean

deb: $(DEB)

$(DEB):
	rm -rf $(BUILDDIR)
	mkdir -p $(BUILDDIR)/DEBIAN
	mkdir -p $(BUILDDIR)/usr/lib/crt-control
	mkdir -p $(BUILDDIR)/usr/bin
	mkdir -p $(BUILDDIR)/usr/share/applications
	mkdir -p $(BUILDDIR)/usr/share/crt-control
	mkdir -p $(BUILDDIR)/etc/systemd/system
	mkdir -p $(BUILDDIR)/etc/xdg/autostart
	# Python files
	cp crt_backend.py $(BUILDDIR)/usr/lib/crt-control/
	cp pi-adc-gui.py $(BUILDDIR)/usr/lib/crt-control/
	cp crt-daemon $(BUILDDIR)/usr/lib/crt-control/
	cp crt-buttons $(BUILDDIR)/usr/lib/crt-control/
	# CLI toggle
	cp crt-toggle $(BUILDDIR)/usr/bin/
	chmod 755 $(BUILDDIR)/usr/bin/crt-toggle
	# Desktop entries
	cp adc-crt-control.desktop $(BUILDDIR)/usr/share/applications/
	cp crt-buttons.desktop $(BUILDDIR)/etc/xdg/autostart/
	# labwc keybinding template
	cp 99-crt-control.xml $(BUILDDIR)/usr/share/crt-control/
	# Systemd service
	cp crt-daemon.service $(BUILDDIR)/etc/systemd/system/
	# Debian metadata
	cp debian/control $(BUILDDIR)/DEBIAN/
	cp debian/postinst $(BUILDDIR)/DEBIAN/
	cp debian/prerm $(BUILDDIR)/DEBIAN/
	dpkg-deb --root-owner-group --build $(BUILDDIR) $(DEB)
	@echo ""
	@echo "Built: $(DEB)"
	@echo "Install with: sudo apt install ./$(DEB)"

clean:
	rm -rf build $(DEB)
