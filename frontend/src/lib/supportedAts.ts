export const SUPPORTED_FILL_REVIEW_ATS = [
    'greenhouse',
    'lever',
    'ashby',
    'smartrecruiters',
    'workday',
    'bamboohr',
    'icims',
    'recruitee',
    'taleo',
] as const;

export function isSupportedFillReviewAts(atsType?: string | null) {
    return SUPPORTED_FILL_REVIEW_ATS.includes(atsType as (typeof SUPPORTED_FILL_REVIEW_ATS)[number]);
}
