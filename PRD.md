We are working on an app that users can send pictures and type messages. I need a AI/ML model with below features. Please do some research and let me know if you are able to do that or not.

Image moderation (nudity / porn):
Please integrate a pretrained image moderation API (e.g. Google Cloud Vision SafeSearch ). All image uploads must be moderated server-side before becoming visible. Images flagged as adult, sexual, or racy above a reasonable confidence threshold should be automatically blocked, deleted, and logged. When in doubt, block the image. No client-side moderation logic.

Text moderation (hate, harassment):
For MVP, do not use AI models. Implement:
Keyword / phrase filtering (slurs, hate speech)
Basic regex rules
User reporting functionality
This is sufficient for initial compliance and risk mitigation. AI-based text moderation can be added later if needed.

Backend expectations:
Image uploads go to temporary private storage
Moderation runs via backend logic (Cloud Functions)
Only approved content is published
Blocked content is logged with reason and timestamp

Explicit non-goals for MVP:
No custom ML model training
No client-side ML
No appeals flow
No partial image blurring

Please confirm:
Which image moderation API you recommend using with Firebase (Please also give me pricing to be able to compare )
Estimated cost per 1k images
Where moderation logic will live in the backend
Timeline impact (if any)