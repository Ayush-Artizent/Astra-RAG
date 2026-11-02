# Email: Plan to upgrade GPL to Guava 33.7.2

From: Release Manager
To: All platform leads
Date: 2025-12-04
Subject: Plan to upgrade GPL to Guava 33.7.2

## Plan

We will move from 32.1.3 to 33.7.2 in two steps. Release candidate 33.7.2-jre-acme.1-rc.1 goes to staging on 2026-02-02. General availability of 33.7.2-jre-acme.1 is targeted for 2026-02-27.

## Compatibility

japicmp shows no incompatible changes in com.acme.platform.guava. Three upstream methods in com.google.common.io were deprecated in the interval. Open: whether the android flavor ships in the same train is to decide.
