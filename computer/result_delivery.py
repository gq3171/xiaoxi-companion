"""Short presentation notices derived from real, ready visual manifests."""
import re


def spoken_result(job):
    if job.get('state') != 'succeeded':
        return job.get('message', '')
    visual = next((item for item in job.get('media', []) if item.get('kind') in ('image', 'video')), None)
    if not visual:
        return job.get('message', '')
    title = re.sub(r'[\x00-\x1f\x7f《》<>]', '', str(visual.get('title', ''))).strip()
    if not title or len(title) > 28:
        return '动画做好啦。' if visual['kind'] == 'video' else '画好啦。'
    return '《' + title + '》做好啦。'
