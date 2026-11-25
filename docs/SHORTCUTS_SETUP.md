# Setting up Do Not Disturb for Commit (macOS)

Commit turns Do Not Disturb on and off by running two Shortcuts that **you** create once.
This keeps Commit simple: macOS decides what gets through, using your own allowlist.

## 1. Create "Commit Focus On"
1. Open the **Shortcuts** app.
2. Click **+** (new shortcut).
3. Name it exactly: **`Commit Focus On`**
4. In the search box on the right, type **Set Focus** and add the action.
5. Set it to: **Turn Do Not Disturb On** (leave "Until" as "Turned Off").

## 2. Create "Commit Focus Off"
1. Click **+** again.
2. Name it exactly: **`Commit Focus Off`**
3. Add **Set Focus** and set it to: **Turn Do Not Disturb Off**.

The names must match exactly (capital letters and spaces included).

## 3. Test
In Commit's setup (or menu bar → Settings → Do Not Disturb setup…) click **Test Focus On**, then
**Test Focus Off**. The first time, macOS may ask whether Terminal/VS Code may control Shortcuts — click **Allow**.

You can also test in Terminal:

```bash
shortcuts run "Commit Focus On"
shortcuts run "Commit Focus Off"
```

## 4. Choose who can still reach you ("urgent" = your allowlist)
System Settings → **Focus** → **Do Not Disturb** → **Allowed People** and **Allowed Apps**.
Only these can notify you while Do Not Disturb is on. Commit never reads your messages.

## Troubleshooting
| Problem | Fix |
|---|---|
| "shortcut was not found" | Check the exact name in the Shortcuts app |
| Shortcut exists but does not run | Open it and check the Set Focus action; run it once by hand |
| Nothing happens, no error | System Settings → Privacy & Security → Automation: allow Terminal/VS Code to control Shortcuts / System Events |
