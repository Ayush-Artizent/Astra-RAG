# Email: Re: Cache default size should be 50,000

From: Platform Architect
To: Product Owner
Date: 2026-03-03
Subject: Re: Cache default size should be 50,000

## Reply

ADR-019 is the approved decision: 25,000 entries and a weigher-based option for large values. A default of 50,000 would raise worst-case heap use of the 200 cache regions by roughly 1.4 GB on the standard 8 GB service profile. I cannot accept it without a change request and benchmark.

## Action

Please raise a change request if you still want 50,000. Open: no CR has been filed as of this date.
