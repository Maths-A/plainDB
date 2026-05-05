package com.plaindb.dbeaver.policy;

import java.util.Locale;

public final class EnglishOnlyGuard {
    public boolean isEnglishOnly(String text) {
        if (text == null || text.isBlank()) {
            return false;
        }

        String normalized = text.toLowerCase(Locale.ROOT);
        if (containsNonAscii(normalized)) {
            return false;
        }

        return containsLatinLetters(normalized);
    }

    private boolean containsNonAscii(String text) {
        for (int index = 0; index < text.length(); index++) {
            if (text.charAt(index) > 127) {
                return true;
            }
        }
        return false;
    }

    private boolean containsLatinLetters(String text) {
        int letterCount = 0;
        for (int index = 0; index < text.length(); index++) {
            char ch = text.charAt(index);
            if (ch >= 'a' && ch <= 'z') {
                letterCount++;
                if (letterCount >= 2) {
                    return true;
                }
            }
        }
        return false;
    }
}
