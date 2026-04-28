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

        return containsEnglishSignal(normalized);
    }

    private boolean containsNonAscii(String text) {
        for (int index = 0; index < text.length(); index++) {
            if (text.charAt(index) > 127) {
                return true;
            }
        }
        return false;
    }

    private boolean containsEnglishSignal(String text) {
        return text.contains(" please ")
            || text.startsWith("please ")
            || text.contains(" update ")
            || text.contains(" insert ")
            || text.contains(" delete ")
            || text.contains(" show ")
            || text.contains(" list ")
            || text.contains(" change ")
            || text.contains(" create ")
            || text.contains(" find ")
            || text.contains(" user ");
    }
}
