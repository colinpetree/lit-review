// Shown on the key pages when the saved-keys file exists but cannot be read.
export default function KeyStoreNotice() {
  return (
    <p
      role="alert"
      className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-900/20 dark:text-red-300"
    >
      Your saved API keys could not be read, so they are shown as missing. A copy of the
      unreadable file is kept in the app's settings folder. Saving a key again starts a fresh
      store; you will need to enter each key again.
    </p>
  )
}
