# DuoRoster

Windows desktop app for two-person monthly shift planning. Tkinter UI and OR-Tools calculation run offline. GitHub is for code and binary releases only.

- Never commit actual names, workbooks, schedules, requests, state files, credentials, or development screenshots. Use synthetic fixtures. Runtime data belongs in the user's AppData, outside the installed program.
- Allowed daily pairs: D/E, E/D, MD/OFF, OFF/MD. Weekend/public-holiday work is MD only. Non-holiday Wednesdays require two workers. E may be followed only by E or OFF. Maximum five consecutive workdays. Monthly OFF counts are exact; the explicit monthly override may exceed the computed minimum. Monthly D/E count differences are each at most three.
- Weekday D after OFF is the lowest-priority preference; E or MD return is allowed and shown as an exception. Special-day MD returns are normal.
- Preserve fixed requests. Never relax hard rules automatically. Distinguish drafts/plans from confirmed actual records used for yearly balancing.
- Updating the app must not replace or remove user data. Verify release checksums, reject path traversal, stage the update, and retain the old application for rollback.
- Use `python -m unittest discover -s tests -v` for core tests and `python main.py --smoke-test` for packaged startup. Changes to month boundaries, manual pairing, update validation, and persistence need meaningful regression coverage.
- UI changes: inspect the native window before/after. Keep input controls plain Korean, large text, and D green / E lime / MD blue / OFF orange.
