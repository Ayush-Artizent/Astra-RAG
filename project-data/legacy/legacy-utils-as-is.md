# Legacy Utils Library As-Is

Date: 2025-05-30
Owner: Platform Architect

## Description

The Legacy Utils Library (LUL) 4.x contains StringUtil, CollectionUtil, CacheUtil and HashUtil used by 63 repositories. It was built on Guava 19.0.

## Pain points

CacheUtil wraps an unbounded map with no expiry. HashUtil uses md5 for deduplication. No Javadoc site exists.

## Retirement plan

LUL is retired in phases through 2026-12-31 as repositories migrate to GPL.
