# Content Moderation System - Setup Guide

This guide covers how to set up and deploy the Content Moderation System.

## Prerequisites

- [Node.js](https://nodejs.org/) 18+ (for Firebase CLI)
- [Python](https://www.python.org/) 3.12+
- [Firebase CLI](https://firebase.google.com/docs/cli)
- Google Cloud account with billing enabled

## 1. Firebase Project Setup

### Create Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Click "Add project"
3. Enter project name
4. Enable Google Analytics (optional)
5. Create project

### Enable Required Services

In Firebase Console:

1. **Authentication**: Enable Email/Password (or your chosen method)
2. **Firestore Database**: Create database in production mode
3. **Storage**: Set up Cloud Storage

### Enable Google Cloud Vision API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your Firebase project
3. Go to "APIs & Services" > "Library"
4. Search for "Cloud Vision API"
5. Click "Enable"

## 2. Local Development Setup

### Clone and Install

```bash
# Navigate to project directory
cd "Image:Messages App"

# Create virtual environment
cd functions
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your values
```

### Firebase Login

```bash
# Install Firebase CLI globally
npm install -g firebase-tools

# Login to Firebase
firebase login

# Initialize project (select existing project)
firebase use --add
```

## 3. Firebase Emulator Setup

The Firebase Emulator Suite allows local development and testing.

### Install Emulators

```bash
# Install required emulators
firebase init emulators
# Select: Functions, Firestore, Storage
```

### Start Emulators

```bash
# From project root
firebase emulators:start

# Emulator UI available at http://localhost:4000
```

### Run Tests with Emulator

```bash
cd functions

# Set emulator environment variables
export FIRESTORE_EMULATOR_HOST="localhost:8080"
export FIREBASE_STORAGE_EMULATOR_HOST="localhost:9199"

# Run tests
pytest
```

## 4. Deploy to Production

### Deploy Functions

```bash
# Deploy all functions
firebase deploy --only functions

# Deploy specific function
firebase deploy --only functions:on_image_upload
```

### Deploy Rules

```bash
# Deploy Firestore rules
firebase deploy --only firestore:rules

# Deploy Storage rules
firebase deploy --only storage:rules
```

### Deploy Everything

```bash
firebase deploy
```

## 5. Configuration

### Moderation Threshold

Set in Firebase Functions configuration:

```bash
# Set to POSSIBLE for stricter moderation
firebase functions:config:set moderation.threshold="POSSIBLE"

# Or LIKELY for default
firebase functions:config:set moderation.threshold="LIKELY"
```

### Rate Limits

```bash
firebase functions:config:set ratelimit.images_per_hour="20"
firebase functions:config:set ratelimit.texts_per_minute="60"
```

### Apply Configuration

After setting config:

```bash
firebase deploy --only functions
```

## 6. Monitoring Setup

### Enable Cloud Monitoring

1. Go to [Cloud Console](https://console.cloud.google.com/)
2. Navigate to "Monitoring"
3. Create a workspace for your project

### Create Alerts

Recommended alerts:

1. **High Block Rate**
   - Metric: Custom (from moderation_logs collection)
   - Condition: Block rate > 20% of uploads
   - Action: Email notification

2. **API Errors**
   - Metric: Cloud Functions errors
   - Condition: Error rate > 5%
   - Action: Email notification

3. **Vision API Quota**
   - Metric: Vision API usage
   - Condition: > 80% of quota
   - Action: Email notification

### View Logs

```bash
# View function logs
firebase functions:log

# View specific function
firebase functions:log --only on_image_upload
```

## 7. Budget Setup

### Set Budget Alert

1. Go to [Cloud Billing](https://console.cloud.google.com/billing)
2. Select your billing account
3. Go to "Budgets & alerts"
4. Create budget with email alerts

Recommended thresholds:
- 50% of budget
- 90% of budget
- 100% of budget

## 8. Updating the Blocklist

### Add Words to Blocklist

Edit `functions/blocklist.txt`:

```
# Add new terms, one per line
newterm
another term
```

### Deploy Updated Blocklist

```bash
firebase deploy --only functions
```

### Use External Blocklist

For production, consider using comprehensive lists:

1. Download from [surge-ai/profanity](https://github.com/surge-ai/profanity)
2. Merge with `blocklist.txt`
3. Deploy

## 9. Troubleshooting

### Common Issues

#### "Permission denied" on Storage upload

- Check Storage rules allow writes to `/pending/{userId}/`
- Ensure user is authenticated
- Verify userId matches authenticated user

#### "Quota exceeded" for Vision API

- Check quota in Cloud Console
- Request quota increase if needed
- Implement queuing for burst traffic

#### Functions timeout

- Increase timeout in `main.py`:
  ```python
  @storage_fn.on_object_finalized(
      timeout_sec=300,  # 5 minutes
  )
  ```

### Debug Mode

Enable verbose logging:

```bash
firebase functions:config:set debug.verbose="true"
firebase deploy --only functions
```

## 10. Security Checklist

Before going to production:

- [ ] Review and test Firestore rules
- [ ] Review and test Storage rules
- [ ] Enable App Check for additional security
- [ ] Set up budget alerts
- [ ] Test rate limiting
- [ ] Verify authentication is required
- [ ] Review blocklist for completeness
- [ ] Test moderation with sample images
- [ ] Set up monitoring alerts

## Support

For issues:
1. Check Firebase status: https://status.firebase.google.com/
2. Check Cloud Vision status: https://status.cloud.google.com/
3. Review function logs: `firebase functions:log`
