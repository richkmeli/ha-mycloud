# Third-party notices

## wdnas-client

The OS5 protocol client in `wdnas.py` is derived from the community
[`wdnas_client`](https://github.com/J-shw/wdnas_client) library. It is not
official Western Digital software.

- Upstream project: <https://github.com/J-shw/wdnas_client>
- Vendored release: `0.9.4`
- Upstream commit: `68bc89983194fdcd15c03d495af59119b592666e`
- License: MIT

Local changes:

- Removed all OS2 code paths, the version selector and the OS2-only
  `latest_version` endpoint.
- Replaced the upstream session creation with the Home Assistant lifecycle in
  `client.py`: a bounded aiohttp session, serialized reconnects, the uptime
  fallback and guarded restart/shutdown actions.
- Split the protocol layer from the integration wrapper and added tests.
- Added the OS5 server-side logout (`DELETE /nas/v1/auth`), so unload,
  reconfigure and re-authentication release the NAS admin session.
- Hardened login by requiring the `PHPSESSID` cookie, fixed group parsing in
  the account response and made missing optional numeric fields default to
  zero instead of raising during parsing. Missing disk and volume IDs,
  textual flags and non-numeric fields are also tolerated.

The following license applies to `wdnas.py` and to the upstream code it is
based on. It does not grant a license for the rest of this repository.

```text
MIT License

Copyright (c) 2019 - 2024  Joakim Sørensen @ludeeus

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
