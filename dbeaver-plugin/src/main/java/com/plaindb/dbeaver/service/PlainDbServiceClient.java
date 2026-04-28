package com.plaindb.dbeaver.service;

import com.plaindb.dbeaver.model.PlainDbDecision;
import com.plaindb.dbeaver.request.PlainDbRequest;

public final class PlainDbServiceClient {
    private final String endpointBaseUrl;

    public PlainDbServiceClient(String endpointBaseUrl) {
        this.endpointBaseUrl = endpointBaseUrl;
    }

    public PlainDbDecision verify(PlainDbRequest request) {
        String message = "Request approved for PlainDB processing.";
        int attempts = 1;

        if (request.getEnglishPrompt() == null || request.getEnglishPrompt().isBlank()) {
            return new PlainDbDecision(false, "Request text is required.", attempts);
        }

        return new PlainDbDecision(true, message, attempts);
    }

    public String getEndpointBaseUrl() {
        return endpointBaseUrl;
    }
}
