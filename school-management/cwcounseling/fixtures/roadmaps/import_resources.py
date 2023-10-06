import os, csv

from cwresources.models import ResourceGroup

path = f"{settings.BASE_DIR}/cwcounseling/fixtures/roadmaps/2_21/resources.csv"
with open(path) as f:
    reader = csv.DictReader(f)
    for row in reader:
        if not row.get("Content"):
            continue
        (resource, _) = Resource.objects.get_or_create(public=True, is_stock=True, title=row.get("Content"))
        # Get or create resource group
        if row.get("Content Category"):
            (resource_group, _) = ResourceGroup.objects.get_or_create(public=True, title=row["Content Category"])
            resource.resource_group = resource_group
        if row.get("Links", "").lower() != "attached":
            resource.link = row.get("Links")
        else:
            print(f"Must update attached resource: {resource.title} {resource.pk}")
        resource.save()
        print(resource)


""" The below script associates resources (created above) with tasks """
path = f"{settings.BASE_DIR}/cwcounseling/fixtures/roadmaps/2_21/tasks_resources.csv"
updated_task_templates = []
with open(path) as f:
    reader = csv.DictReader(f)
    for row in reader:
        if not (row.get("Resource 1") or row.get("Resource 2")):
            continue
        task_name = row.get("Task Names")
        task_templates = TaskTemplate.objects.filter(title__iexact=task_name, roadmap__isnull=False)
        for x in ("Resource 1", "Resource 2"):
            if row.get(x):
                updated_task_templates += list(task_templates.values_list("pk", flat=True))
                resource_one = Resource.objects.get(is_stock=True, title=row.get(x))
                print(resource_one, task_templates.count())
                for t in task_templates:
                    t.resources.add(resource_one)

updated_tt_objects = TaskTemplate.objects.filter(pk__in=updated_task_templates).distinct()

print(f"Updated {updated_tt_objects.count()} task templates")
