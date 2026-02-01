# Content Moderation API Documentation

This document provides the API contract for the Content Moderation System, designed for integration by the iOS development team.

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Image Upload Flow](#image-upload-flow)
4. [Cloud Functions API](#cloud-functions-api)
5. [Firestore Collections](#firestore-collections)
6. [Error Handling](#error-handling)
7. [Rate Limits](#rate-limits)
8. [Cost Estimates](#cost-estimates)

---

## Overview

The Content Moderation System automatically moderates user-uploaded images and text content before they become visible to other users.

### Architecture Summary

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   iOS App   │────▶│ Firebase Storage │────▶│ Cloud Functions │
│             │     │  /pending/...    │     │ (Image Mod)     │
└─────────────┘     └──────────────────┘     └────────┬────────┘
                                                      │
                    ┌──────────────────┐              │
                    │  Vision API      │◀─────────────┘
                    │  SafeSearch      │
                    └──────────────────┘
```

### Key Flows

1. **Image Upload**: Client uploads to `/pending/` → Cloud Function moderates → Approved images moved to `/approved/`
2. **Text Validation**: Client calls `validate_text` function before saving message
3. **Reporting**: Client calls `submit_report` function to report content

---

## Authentication

All API calls require Firebase Authentication. Users must be signed in before:
- Uploading images
- Sending messages
- Submitting reports

```swift
// iOS Example: Ensure user is authenticated
guard let user = Auth.auth().currentUser else {
    // Prompt user to sign in
    return
}
```

---

## Image Upload Flow

### Step 1: Upload to Pending

Upload images to the pending folder. The path format is:

```
/pending/{userId}/{imageId}
```

**iOS Example (Swift)**:

```swift
import FirebaseStorage

func uploadImage(_ imageData: Data, completion: @escaping (Result<String, Error>) -> Void) {
    guard let userId = Auth.auth().currentUser?.uid else {
        completion(.failure(AuthError.notAuthenticated))
        return
    }
    
    let imageId = UUID().uuidString
    let path = "pending/\(userId)/\(imageId)"
    let storageRef = Storage.storage().reference().child(path)
    
    let metadata = StorageMetadata()
    metadata.contentType = "image/jpeg"
    
    storageRef.putData(imageData, metadata: metadata) { metadata, error in
        if let error = error {
            completion(.failure(error))
            return
        }
        completion(.success(imageId))
    }
}
```

### Step 2: Wait for Moderation

After upload, the image is automatically moderated by a Cloud Function. The client should poll or listen for the approved image.

**Polling Approach**:

```swift
func checkImageApproved(userId: String, imageId: String, completion: @escaping (Bool) -> Void) {
    let approvedPath = "approved/\(userId)/\(imageId).jpg"
    let storageRef = Storage.storage().reference().child(approvedPath)
    
    storageRef.downloadURL { url, error in
        completion(url != nil)
    }
}
```

**Recommended: Firestore Listener**

Store image status in Firestore and listen for updates:

```swift
// Listen for image status updates
let docRef = Firestore.firestore()
    .collection("messages")
    .document(messageId)

docRef.addSnapshotListener { snapshot, error in
    guard let data = snapshot?.data(),
          let status = data["imageStatus"] as? String else { return }
    
    switch status {
    case "approved":
        // Load image from /approved/
    case "blocked":
        // Show "Image not available" placeholder
    case "pending":
        // Show loading spinner
    default:
        break
    }
}
```

### Step 3: Retrieve Approved Image

Approved images are available at:

```
/approved/{userId}/{imageId}.jpg   (compressed)
/thumbnails/{userId}/{imageId}.jpg (thumbnail, 200x200 max)
```

```swift
func getApprovedImageURL(userId: String, imageId: String, completion: @escaping (URL?) -> Void) {
    let path = "approved/\(userId)/\(imageId).jpg"
    Storage.storage().reference().child(path).downloadURL { url, error in
        completion(url)
    }
}

func getThumbnailURL(userId: String, imageId: String, completion: @escaping (URL?) -> Void) {
    let path = "thumbnails/\(userId)/\(imageId).jpg"
    Storage.storage().reference().child(path).downloadURL { url, error in
        completion(url)
    }
}
```

---

## Cloud Functions API

### validate_text

Validates text content before saving to Firestore.

**Call Type**: HTTPS Callable

**Request**:
```json
{
  "text": "string (required) - The text to validate",
  "context": "string (optional) - Conversation ID or other context"
}
```

**Response**:
```json
{
  "allowed": true,
  "reason": null
}
```

or

```json
{
  "allowed": false,
  "reason": "Content contains prohibited terms: ..."
}
```

**iOS Example**:

```swift
import FirebaseFunctions

func validateText(_ text: String, completion: @escaping (Bool, String?) -> Void) {
    let functions = Functions.functions()
    
    functions.httpsCallable("validate_text").call(["text": text]) { result, error in
        if let error = error as NSError? {
            if error.domain == FunctionsErrorDomain {
                let code = FunctionsErrorCode(rawValue: error.code)
                let message = error.localizedDescription
                completion(false, message)
                return
            }
        }
        
        guard let data = result?.data as? [String: Any],
              let allowed = data["allowed"] as? Bool else {
            completion(false, "Invalid response")
            return
        }
        
        let reason = data["reason"] as? String
        completion(allowed, reason)
    }
}

// Usage
func sendMessage(_ text: String) {
    validateText(text) { allowed, reason in
        if allowed {
            // Save message to Firestore
            saveMessageToFirestore(text)
        } else {
            // Show error to user
            showAlert("Message not sent", message: reason ?? "Content not allowed")
        }
    }
}
```

---

### submit_report

Submit a user report for inappropriate content.

**Call Type**: HTTPS Callable

**Request**:
```json
{
  "messageId": "string (required) - ID of the message being reported",
  "category": "string (required) - One of: spam, harassment, inappropriate, other",
  "description": "string (optional) - Additional details, max 1000 chars"
}
```

**Response (Success)**:
```json
{
  "success": true,
  "reportId": "abc123..."
}
```

**Response (Error)**:
```json
{
  "success": false,
  "error": "Rate limit exceeded..."
}
```

**iOS Example**:

```swift
enum ReportCategory: String {
    case spam = "spam"
    case harassment = "harassment"
    case inappropriate = "inappropriate"
    case other = "other"
}

func submitReport(
    messageId: String,
    category: ReportCategory,
    description: String? = nil,
    completion: @escaping (Result<String, Error>) -> Void
) {
    let functions = Functions.functions()
    
    var data: [String: Any] = [
        "messageId": messageId,
        "category": category.rawValue
    ]
    
    if let description = description {
        data["description"] = description
    }
    
    functions.httpsCallable("submit_report").call(data) { result, error in
        if let error = error {
            completion(.failure(error))
            return
        }
        
        guard let data = result?.data as? [String: Any],
              let success = data["success"] as? Bool,
              success,
              let reportId = data["reportId"] as? String else {
            completion(.failure(NSError(domain: "Report", code: -1)))
            return
        }
        
        completion(.success(reportId))
    }
}
```

---

### get_rate_limits

Get current rate limit status for the authenticated user.

**Call Type**: HTTPS Callable

**Request**: None (uses authenticated user)

**Response**:
```json
{
  "image_upload": {
    "current": 5,
    "limit": 20,
    "remaining": 15,
    "resetAt": "2024-01-15T11:00:00Z",
    "windowSeconds": 3600
  },
  "text_message": {
    "current": 10,
    "limit": 60,
    "remaining": 50,
    "resetAt": "2024-01-15T10:31:00Z",
    "windowSeconds": 60
  },
  "report": {
    "current": 2,
    "limit": 10,
    "remaining": 8,
    "resetAt": "2024-01-15T11:00:00Z",
    "windowSeconds": 3600
  }
}
```

---

## Firestore Collections

### messages (Example Structure)

```javascript
{
  "id": "msg123",
  "senderId": "user123",
  "conversationId": "conv456",
  "text": "Hello!",
  "imageId": "img789",  // Optional
  "imageStatus": "approved" | "pending" | "blocked",
  "timestamp": Timestamp
}
```

### Storage Rules

The storage rules enforce:
- Users can only upload to their own `/pending/{userId}/` folder
- Maximum file size: 25 MB
- Only image MIME types allowed
- Users cannot read pending images
- All users can read approved images

---

## Error Handling

### Common Error Codes

| Code | Description | User Action |
|------|-------------|-------------|
| `UNAUTHENTICATED` | User not signed in | Prompt sign in |
| `RESOURCE_EXHAUSTED` | Rate limit exceeded | Show retry time |
| `INVALID_ARGUMENT` | Invalid request data | Fix request |
| `INTERNAL` | Server error | Retry later |

### Error Response Format

```json
{
  "code": "RESOURCE_EXHAUSTED",
  "message": "Rate limit exceeded. Try again at 2024-01-15T11:00:00Z"
}
```

### iOS Error Handling Example

```swift
func handleFunctionsError(_ error: Error) -> String {
    let nsError = error as NSError
    
    if nsError.domain == FunctionsErrorDomain {
        switch FunctionsErrorCode(rawValue: nsError.code) {
        case .unauthenticated:
            return "Please sign in to continue"
        case .resourceExhausted:
            return "Too many requests. Please wait and try again."
        case .invalidArgument:
            return nsError.localizedDescription
        default:
            return "Something went wrong. Please try again."
        }
    }
    
    return "Network error. Check your connection."
}
```

---

## Rate Limits

| Action | Limit | Window |
|--------|-------|--------|
| Image Upload | 20 | per hour |
| Text Message | 60 | per minute |
| Report | 10 | per hour |

### Handling Rate Limits in UI

```swift
// Check limits before showing upload button
func updateUploadButton() {
    Functions.functions().httpsCallable("get_rate_limits").call(nil) { result, _ in
        guard let data = result?.data as? [String: Any],
              let imageLimit = data["image_upload"] as? [String: Any],
              let remaining = imageLimit["remaining"] as? Int else { return }
        
        DispatchQueue.main.async {
            self.uploadButton.isEnabled = remaining > 0
            if remaining == 0 {
                self.uploadButton.setTitle("Upload limit reached", for: .disabled)
            }
        }
    }
}
```

---

## Cost Estimates

### Google Cloud Vision API

| Volume | Cost per 1,000 |
|--------|----------------|
| First 1,000/month | Free |
| 1,001 - 5,000,000/month | $1.50 |

### Estimated Monthly Costs

For 1,000 active users uploading 5 images/day:

- **Images**: 150,000/month
- **Vision API Cost**: ~$224/month
- **Storage**: ~$5-10/month (depending on image sizes)
- **Cloud Functions**: ~$10-20/month

---

## Setup Checklist for iOS Team

1. [ ] Add Firebase SDK to iOS project
2. [ ] Configure Firebase Authentication
3. [ ] Configure Firebase Storage
4. [ ] Configure Firebase Functions
5. [ ] Implement image upload to `/pending/`
6. [ ] Implement `validate_text` call before sending messages
7. [ ] Implement `submit_report` for reporting UI
8. [ ] Handle rate limit errors gracefully
9. [ ] Implement loading states while images are being moderated

---

## Contact

For questions about this API, contact the backend team.
