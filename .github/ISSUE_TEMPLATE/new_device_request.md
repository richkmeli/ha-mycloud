---
name: New Device Support Request
about: Request support for a new WD My Cloud model or firmware version.
title: "Add support for [DEVICE MODEL]"
labels: new device, enhancement
assignees: ""
---

### 1. Device model

Full model name of your WD My Cloud (for example: My Cloud EX2 Ultra, WD My Cloud Mirror Gen 2).

**Model:**

### 2. Firmware version

Find it in the NAS web interface, usually under **Settings → Firmware**.

**Firmware:**

### 3. System version (V2 / V5)

Which version did you select during the integration setup?

**Version:**

### 4. Integration version

Find it in **HACS → Integrations → WD My Cloud** or in the diagnostics download.

**Version:**

### 5. Debug logs

Enable debug logging, reproduce the problem and paste the relevant lines here. Remove the password, serial numbers and any other personal data first.

```yaml
logger:
  default: warning
  logs:
    custom_components.mycloud: debug
```

**Logs:**
