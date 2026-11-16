# Security

This repository is a fork of [bmarsh9/gapps](https://github.com/bmarsh9/gapps). Report security
problems in **this fork** here, and problems that also exist in the original to the original project.

## Reporting a vulnerability

Please report it **privately**, not in a public issue:

1. Go to the [Security tab](https://github.com/1968-Larry/gapps/security) of this repository
2. Choose **Report a vulnerability** and describe the problem, how to reproduce it and the impact

You will get an answer through the advisory. Once a fix is available it is published in this
repository, and the advisory is made public if that helps users of the fork.

## What is covered

The code in this repository: the Flask application, the templates and the scripts. Third-party
libraries are kept up to date with Dependabot and checked by the CI workflow (pip-audit, npm audit).
