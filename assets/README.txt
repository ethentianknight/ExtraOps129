EXTRA OPS 129 v0.2.1
Character models and four-player co-op for Metal Gear Solid: Peace Walker

SETUP
1. Restore any older EO129 or Co-op 4 test with that package's own installer.
2. Steam > Peace Walker > Manage > Browse local files.
3. Copy this complete Extra Ops 129 folder beside the mgspw folder.
4. Close Peace Walker and run Setup Extra Ops 129.cmd.
5. Choose one installation mode:
     1: Install models
     2: Install 4-player co-op
     3: Install models and 4-player co-op

PLAY
Run Play Extra Ops 129.cmd for every modded session. It opens Steam. Start Peace
Walker through its launcher. The one helper reads the installed mode and applies
the model hook, co-op spawn hook, or both. Wait for the active message before
selecting a mission. The helper can then close. Runtime changes vanish on exit.

MODELS
Edit character_config.txt before Play. 0 leaves an outfit unchanged. See
Roster.txt for choices. Snake is unaffected. Model archive files remain installed
until Uninstall all, but launching directly through Steam omits runtime mappings.

FOUR-PLAYER CO-OP
Every verified mission record originally capped at two becomes four except Main
Op 20, Torture Chamber Escape, which remains two. Original one-player and
four-player records remain unchanged. All participating PCs need the same mode
installed and must use Play Extra Ops 129.cmd each session. Standard and prison
co-op resources are expanded. Players 3/4 reuse placements 1/2 when a co-op room
provides only two placement entries. Room transitions, cutscenes, special scripts,
and every individual mission are not fully validated; this remains a test build.

REMOVE AND SAVES
Run Setup Extra Ops 129.cmd and choose:
     4: Uninstall all
     5: Uninstall all and restore save
     6: Restore save only
Uninstall always restores all three original archives, regardless of installed
mode. Reinstall a specific mode afterward if desired. Installation creates and
verifies a complete local save backup. Before using option 5 or 6, open the game Properties in Steam and disable Steam
Cloud for Peace Walker. Then exit Steam completely and run the restore. The
installer preserves another copy of current saves, verifies the restored files
after replacement, and refreshes their local timestamps. Restart Steam only after
restore completes. If Steam reports a conflict, keep the local files.

MANUAL BACKUPS
  mgspw\MLG\disc0_rel\002aba34.DAT
  mgspw\MLG\disc0_rel\002aba34.KEY
  mgspw\MLG\disc0_rel\009645fa.PDT
  mgspw_savedata_win (entire directory)
The installer also stores verified originals under this package's backups folder.
Keep the installed folder and its backups. Never share backups or save-backups.

REQUIREMENTS
Verified Steam build 25052315. No Python or downloads required. Installation
refuses modified or unsupported archives. Use each older package to uninstall its
own changes before installing this release. Source and build instructions are in
the separate source package.
