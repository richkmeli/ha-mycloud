---
name: Bug report
about: Report a problem with the WD My Cloud integration.
title: "[Bug]: "
labels: bug
assignees: ""
---

### Checklist

- [ ] I am running the latest release from `richkmeli/ha-mycloud`.
- [ ] I am using an admin account.
- [ ] I checked the existing issues and the troubleshooting section of the README.
- [ ] I removed passwords, serial numbers and other personal data from the logs.

### Describe the bug

A clear and concise description of the problem.

### Steps to reproduce

1.
2.
3.

### Expected behaviour

What did you expect to happen?

### Environment

- Home Assistant version:
- Integration version:
- NAS model:
- NAS firmware:
- OS version (2 or 5):

### Diagnostics

Download **Settings → Devices & services → WD My Cloud → Download diagnostics** and attach the JSON file. The password is redacted automatically.

### Logs

```yaml
logger:
  default: warning
  logs:
    custom_components.mycloud: debug
```

```text

```
