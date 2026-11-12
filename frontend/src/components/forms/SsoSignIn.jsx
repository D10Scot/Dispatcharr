import React from 'react';
import { Button, Stack, Text } from '@mantine/core';
import { ssoErrorMessage, ssoStartUrl } from '../../utils/sso/ssoUtils';

// Provider buttons and the fixed-copy sign-in error. Everything that comes from
// the server or the URL is rendered as text by React, never as HTML, and the
// error is looked up in a fixed table (unknown codes get a generic message).
const SsoSignIn = ({ providers = [], errorCode = null, next = null }) => {
  const start = (slug) => {
    // A top-level navigation, never fetch or XHR: the provider answers with a redirect.
    window.location.href = ssoStartUrl(slug, next);
  };

  return (
    <Stack gap="xs" data-testid="sso-signin" style={{ width: '100%' }}>
      {errorCode && (
        <Text size="sm" c="red" role="alert" data-testid="sso-error">
          {ssoErrorMessage(errorCode)}
        </Text>
      )}
      {providers.map((provider) => (
        <Button
          key={provider.slug}
          variant="default"
          fullWidth
          onClick={() => start(provider.slug)}
          data-testid={`sso-login-${provider.slug}`}
        >
          {`Sign in with ${provider.display_name}`}
        </Button>
      ))}
    </Stack>
  );
};

export default SsoSignIn;
